from decimal import Decimal, InvalidOperation
import logging
from urllib.parse import quote, urlsplit
import uuid

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone

from .models import Order, Payment


logger = logging.getLogger(__name__)


class PaystackError(Exception):
    """A Paystack request or response could not be safely processed."""


def paystack_is_enabled():
    if not settings.PAYSTACK_PUBLIC_KEY and not settings.PAYSTACK_SECRET_KEY:
        return False
    if not settings.PAYSTACK_PUBLIC_KEY or not settings.PAYSTACK_SECRET_KEY:
        logger.error("Paystack requires both a public key and a secret key.")
        return False
    try:
        validate_paystack_configuration()
    except ImproperlyConfigured:
        logger.exception("Paystack payment is disabled because its key configuration is invalid.")
        return False
    return True


def validate_paystack_configuration():
    public_key = settings.PAYSTACK_PUBLIC_KEY
    secret_key = settings.PAYSTACK_SECRET_KEY
    if not public_key or not secret_key:
        raise PaystackError("Paystack is not fully configured.")

    public_mode = "test" if public_key.startswith("pk_test_") else "live" if public_key.startswith("pk_live_") else None
    secret_mode = "test" if secret_key.startswith("sk_test_") else "live" if secret_key.startswith("sk_live_") else None
    if public_mode is None or secret_mode is None or public_mode != secret_mode:
        raise ImproperlyConfigured("Paystack public and secret keys must be valid, matching test or live keys.")
    if settings.PAYSTACK_LIVE_MODE and secret_mode != "live":
        raise ImproperlyConfigured("PAYSTACK_LIVE_MODE=True requires matching live Paystack keys.")
    if secret_mode == "live" and not settings.PAYSTACK_LIVE_MODE:
        raise ImproperlyConfigured("Live Paystack keys are disabled. Set PAYSTACK_LIVE_MODE=True only after live payments are authorized.")


def paystack_is_test_mode():
    return settings.PAYSTACK_SECRET_KEY.startswith("sk_test_")


def _headers():
    validate_paystack_configuration()
    return {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }


def amount_in_subunits(amount):
    try:
        value = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as error:
        raise PaystackError("The payment amount is invalid.") from error
    if not value.is_finite() or value <= 0:
        raise PaystackError("The payment amount must be positive and have no more than two decimal places.")
    subunits = value * 100
    if subunits != subunits.to_integral_value():
        raise PaystackError("The payment amount must be positive and have no more than two decimal places.")
    return int(subunits)


def _request_data(response, action):
    try:
        response.raise_for_status()
    except requests.RequestException as error:
        raise PaystackError(f"Unable to {action} with Paystack.") from error
    try:
        payload = response.json()
    except ValueError as error:
        raise PaystackError(f"Paystack returned an unreadable response while trying to {action}.") from error
    if not isinstance(payload, dict) or not payload.get("status") or not isinstance(payload.get("data"), dict):
        message = payload.get("message") if isinstance(payload, dict) else None
        raise PaystackError(message or f"Paystack could not {action}.")
    return payload["data"]


def generate_payment_reference(order):
    return f"{order.number}-{uuid.uuid4().hex.upper()}"


def initialize_transaction(*, email, amount, reference, callback_url):
    payload = {
        "email": email,
        "amount": amount_in_subunits(amount),
        "currency": settings.PAYSTACK_CURRENCY,
        "reference": reference,
        "callback_url": callback_url,
    }
    try:
        response = requests.post(
            f"{settings.PAYSTACK_BASE_URL}/transaction/initialize",
            json=payload,
            headers=_headers(),
            timeout=(3.05, 15),
        )
    except requests.RequestException as error:
        raise PaystackError("Unable to connect to Paystack to initialize payment.") from error
    data = _request_data(response, "initialize the payment")

    authorization_url = data.get("authorization_url")
    try:
        parsed_url = urlsplit(authorization_url) if isinstance(authorization_url, str) else None
    except ValueError as error:
        raise PaystackError("Paystack returned an invalid checkout URL.") from error
    if (
        not parsed_url
        or parsed_url.scheme != "https"
        or parsed_url.hostname != "checkout.paystack.com"
        or parsed_url.username
        or parsed_url.password
        or data.get("reference") != reference
    ):
        raise PaystackError("Paystack returned an invalid checkout URL or payment reference.")
    return data


def verify_transaction(reference):
    try:
        response = requests.get(
            f"{settings.PAYSTACK_BASE_URL}/transaction/verify/{quote(reference, safe='')}",
            headers=_headers(),
            timeout=(3.05, 15),
        )
    except requests.RequestException as error:
        raise PaystackError("Unable to connect to Paystack to verify payment.") from error
    return _request_data(response, "verify the payment")


def record_verified_transaction(payment_id, data):
    with transaction.atomic():
        # Lock the order first, just like quote confirmation and initialization.
        order_id = Payment.objects.values_list("order_id", flat=True).get(pk=payment_id)
        order = Order.objects.select_for_update().get(pk=order_id)
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        valid_amount = (
            type(data.get("amount")) is int
            and data["amount"] == amount_in_subunits(payment.amount)
        )
        if (
            data.get("reference") != payment.reference
            or data.get("currency") != payment.currency
            or not valid_amount
        ):
            return False

        provider_status = data.get("status")
        if payment.status == Payment.Status.SUCCESS:
            return True

        if (payment.invalidated_at is not None or not order.quote_confirmed
                or order.payment_status != Order.PaymentStatus.UNPAID
                or payment.amount != order.total
                or order.payments.filter(status=Payment.Status.SUCCESS).exists()):
            logger.warning("Rejected stale or ineligible payment reference %s; reconcile any provider charge manually.", payment.reference)
            return False

        if provider_status == "success":
            payment.status = Payment.Status.SUCCESS
            payment.paid_at = timezone.now()
            order.payment_status = Order.PaymentStatus.PAID
            order.save(update_fields={"payment_status", "updated_at"})
        elif provider_status == "failed":
            payment.status = Payment.Status.FAILED
        elif provider_status == "abandoned":
            payment.status = Payment.Status.ABANDONED
        else:
            return True

        transaction_id = data.get("id")
        payment.provider_transaction_id = str(transaction_id) if transaction_id is not None else ""
        payment.provider_response = {
            key: data.get(key)
            for key in ("reference", "status", "amount", "currency", "id")
            if data.get(key) is not None
        }
        payment.save(update_fields={
            "status", "paid_at", "provider_transaction_id",
            "provider_response", "updated_at",
        })
        return True
