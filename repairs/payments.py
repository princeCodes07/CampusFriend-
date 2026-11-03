from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from orders.payments import (
    PaystackError,
    amount_in_subunits,
    initialize_transaction,
    validate_paystack_configuration,
    verify_transaction,
)

from .models import (
    PhoneRepairPrice,
    RepairPayment,
    RepairRequest,
    RepairStatusHistory,
)

FIXED_PRICE_SERVICE_SLUGS = {
    "fix-broken-screen",
    "change-screen",
    "fix-charging-system",
    "repair-speaker",
    "change-housing-backglass",
}


class RepairPaymentError(Exception):
    """A repair is not currently eligible for payment."""


class RepairPriceChanged(RepairPaymentError):
    """The current catalogue price differs from the student's confirmation."""


def current_repair_price(repair_request):
    if repair_request.request_type != RepairRequest.RequestType.FIXED_PRICE_PHONE:
        raise RepairPaymentError("Payment is not required for this repair request yet. Our team will contact you first.")
    service = repair_request.service
    phone_model = repair_request.phone_model
    if (
        service is None
        or service.slug not in FIXED_PRICE_SERVICE_SLUGS
        or not service.active
        or not service.priceable
        or phone_model is None
        or not phone_model.active
        or phone_model.phone_type != repair_request.phone_type
    ):
        raise RepairPaymentError("This repair is no longer eligible for online payment.")
    price = PhoneRepairPrice.objects.filter(
        service=service,
        phone_model=phone_model,
        active=True,
        price__gt=Decimal("0.00"),
    ).first()
    if price is None:
        raise RepairPaymentError("The repair price is no longer available. Please contact us before paying.")
    return price


def create_payment_attempt(repair_request_id, email):
    with transaction.atomic():
        repair_request = RepairRequest.objects.select_for_update().select_related(
            "service", "phone_model"
        ).get(pk=repair_request_id)
        if repair_request.status == RepairRequest.Status.PAID or repair_request.payments.filter(
            status=RepairPayment.Status.PAID
        ).exists():
            raise RepairPaymentError("This repair has already been paid.")
        if repair_request.status not in {
            RepairRequest.Status.PRICE_CONFIRMED,
            RepairRequest.Status.PAYMENT_PENDING,
        }:
            raise RepairPaymentError("This repair is not ready for payment.")

        price = current_repair_price(repair_request)
        if repair_request.confirmed_price != price.price:
            raise RepairPriceChanged("The repair price has changed. Review and confirm the updated price before paying.")

        latest_pending = repair_request.payments.filter(
            status=RepairPayment.Status.PENDING
        ).first()
        if latest_pending is not None:
            return latest_pending, False

        payment = RepairPayment.objects.create(
            repair_request=repair_request,
            amount=price.price,
            currency=settings.PAYSTACK_CURRENCY,
        )
        if repair_request.email != email:
            repair_request.email = email
            repair_request.save(update_fields={"email", "updated_at"})
        if repair_request.status != RepairRequest.Status.PAYMENT_PENDING:
            repair_request.transition_to(
                RepairRequest.Status.PAYMENT_PENDING,
                note="Full payment initiated.",
            )
        return payment, True


def mark_initialization_failed(payment_id):
    RepairPayment.objects.filter(
        pk=payment_id,
        status=RepairPayment.Status.PENDING,
    ).update(status=RepairPayment.Status.FAILED, updated_at=timezone.now())


def record_verified_transaction(payment_id, data):
    with transaction.atomic():
        payment = RepairPayment.objects.select_for_update().select_related(
            "repair_request"
        ).get(pk=payment_id)
        repair_request = RepairRequest.objects.select_for_update().get(
            pk=payment.repair_request_id
        )
        try:
            valid_amount = (
                type(data.get("amount")) is int
                and data["amount"] == amount_in_subunits(payment.amount)
            )
        except (KeyError, PaystackError):
            valid_amount = False
        if (
            data.get("reference") != payment.reference
            or data.get("currency") != payment.currency
            or not valid_amount
        ):
            return False

        provider_status = data.get("status")
        if payment.status == RepairPayment.Status.PAID:
            return provider_status == "success"
        if repair_request.status not in {
            RepairRequest.Status.PAYMENT_PENDING,
            RepairRequest.Status.PAID,
        }:
            return False

        if provider_status == "success":
            payment.status = RepairPayment.Status.PAID
            payment.paid_at = timezone.now()
        elif provider_status == "failed":
            payment.status = RepairPayment.Status.FAILED
        elif provider_status == "abandoned":
            payment.status = RepairPayment.Status.ABANDONED
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
        if provider_status == "success" and repair_request.status != RepairRequest.Status.PAID:
            repair_request.transition_to(
                RepairRequest.Status.PAID,
                note="Full payment received and verified.",
            )
        return True


__all__ = [
    "PaystackError",
    "RepairPaymentError",
    "RepairPriceChanged",
    "amount_in_subunits",
    "create_payment_attempt",
    "current_repair_price",
    "initialize_transaction",
    "mark_initialization_failed",
    "record_verified_transaction",
    "validate_paystack_configuration",
    "verify_transaction",
]