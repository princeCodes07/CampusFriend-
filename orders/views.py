import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django import forms
from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe, require_http_methods

from store.catalog import visible_products

from .cart import CART_SESSION_KEY, get_cart
from .delivery import LOCATION_CHOICES
from .forms import AddToCartForm, CheckoutForm
from .models import Order, Payment
from .payments import (
    PaystackError,
    initialize_transaction,
    paystack_is_enabled,
    paystack_is_test_mode,
    record_verified_transaction,
    validate_paystack_configuration,
    verify_transaction,
)
from .services import (
    CheckoutError,
    attach_payment_checkout,
    create_payment_attempt,
    create_pending_order,
    delivery_fees,
    quote_fingerprint,
    validate_order_stock,
)


GUEST_SESSION_KEY = "order_guest_id"
PREVIEW_SESSION_KEY = "checkout_preview"
logger = logging.getLogger(__name__)


def _guest_id(request):
    value = request.session.get(GUEST_SESSION_KEY)
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def _checkout_preview(request, cart, fees):
    fingerprint = quote_fingerprint(cart.items, fees)
    previous = request.session.get(PREVIEW_SESSION_KEY, {})
    if not isinstance(previous, dict) or previous.get("fingerprint") != fingerprint:
        previous = {"token": str(uuid.uuid4()), "fingerprint": fingerprint}
        request.session[PREVIEW_SESSION_KEY] = previous
    return previous


@require_safe
def cart_detail(request):
    return render(request, "orders/cart.html", {"cart": get_cart(request)})


@require_safe
def track(request):
    """Keep the old tracking URL within Orders without a second tracking page."""
    return redirect("orders:order_list", permanent=True)


@require_safe
def order_list(request):
    guest_id = _guest_id(request)
    orders = (
        Order.objects.filter(guest_id=guest_id).prefetch_related("items")
        if guest_id else Order.objects.none()
    )
    return render(request, "orders/order_list.html", {
        "orders": orders,
        "nav_section": "orders",
    })


@require_POST
def cart_add(request, product_id):
    product = get_object_or_404(visible_products(), pk=product_id)
    form = AddToCartForm(request.POST)
    if not form.is_valid():
        messages.error(request, form.errors["quantity"][0])
        return redirect(product)

    cart = get_cart(request)
    quantity = form.cleaned_data["quantity"]
    try:
        cart.add(product, quantity)
    except ValueError as error:
        messages.error(request, str(error))
        return redirect(product)

    messages.success(request, f"Added {quantity} × {product.name} to your cart.")
    # Buy now uses the same validated cart mutation and a fixed local destination.
    if request.POST.get("action") == "buy_now":
        return redirect("orders:checkout")
    return redirect("orders:cart_detail")


@require_POST
def cart_remove(request, product_id):
    if get_cart(request).remove(product_id):
        messages.success(request, "Item removed from your cart.")
    return redirect("orders:cart_detail")


@never_cache
@require_http_methods(["GET", "POST"])
def checkout(request):
    error = None
    if request.method == "POST":
        # A completed checkout stays idempotent even if delivery pricing later changes.
        try:
            submitted_token = uuid.UUID(request.POST.get("checkout_token", ""))
        except (ValueError, TypeError, AttributeError):
            submitted_token = None
        guest_id = _guest_id(request)
        existing = Order.objects.filter(guest_id=guest_id, checkout_token=submitted_token).first() if guest_id and submitted_token else None
        if existing:
            return redirect(existing)
        submitted = CheckoutForm(request.POST)
        if submitted.is_valid():
            token = submitted.cleaned_data["checkout_token"]
            guest_id = _guest_id(request)
            preview = request.session.get(PREVIEW_SESSION_KEY, {})
            if not isinstance(preview, dict) or preview.get("token") != str(token):
                error = "This checkout has expired or changed. Review the summary and submit again."
            else:
                try:
                    order, created = create_pending_order(
                        guest_id=guest_id, checkout_token=token,
                        quantities=request.session.get(CART_SESSION_KEY),
                        expected_fingerprint=preview.get("fingerprint"), customer=submitted.cleaned_data,
                    )
                except CheckoutError as failure:
                    error = str(failure)
                else:
                    if created:
                        request.session.pop(CART_SESSION_KEY, None)
                        request.session.pop(PREVIEW_SESSION_KEY, None)
                    return redirect(order)
        else:
            error = "Please check the details below and submit again."

    # Reconcile only after attempting checkout: never silently buy a reduced cart.
    cart = get_cart(request)
    if not cart.count:
        messages.error(request, error or "Add an in-stock product before starting checkout.")
        return redirect("orders:cart_detail")
    if not _guest_id(request):
        request.session[GUEST_SESSION_KEY] = str(uuid.uuid4())
    fees = delivery_fees()
    preview = _checkout_preview(request, cart, fees)
    data = request.POST.copy() if request.method == "POST" else None
    if data is not None:
        # Retain customer input while replacing an expired preview token for retry.
        data["checkout_token"] = preview["token"]
    form = CheckoutForm(data, initial={"checkout_token": preview["token"]})
    if error:
        form.is_valid()
        form.add_error(None, error)
    quote_notes = {
        "campus": "Campus delivery is free.",
        "pickup": "Collect your order at Palms Eatery. There is no delivery charge.",
        "other": "Pay for your items now. Delivery is not included in this payment; the fee will be discussed and agreed with you separately.",
    }
    # Publish server-calculated amounts as data, not seven visible summaries.
    delivery_quotes = {
        area: {"label": label, "fee": f"{fees[area]:.2f}",
               "total": f"{cart.subtotal + fees[area]:.2f}",
               "delivery_fee_separate": area == "other", "note": quote_notes.get(area, "")}
        for area, label in LOCATION_CHOICES
    }
    return render(request, "orders/checkout.html", {
        "form": form, "cart": cart,
        "paystack_enabled": paystack_is_enabled(),
        "delivery_quotes": delivery_quotes,
        "selected_quote": delivery_quotes.get(form["delivery_area"].value()),
    })


@never_cache
@require_safe
def confirmation(request, number):
    guest_id = _guest_id(request)
    if not guest_id:
        raise Http404("Order not found")
    order = get_object_or_404(
        Order.objects.prefetch_related("items", "status_history", "payments"),
        number=number,
        guest_id=guest_id,
    )
    status_history = list(order.status_history.all())
    payments = list(order.payments.all())
    return render(request, "orders/confirmation.html", {
        "order": order,
        "status_history": status_history,
        "status_history_matches_current": bool(
            status_history and status_history[-1].status == order.status
        ),
        "latest_payment": payments[0] if payments else None,
        "successful_payment": next(
            (payment for payment in payments if payment.status == Payment.Status.SUCCESS),
            None,
        ),
        "paystack_enabled": paystack_is_enabled(),
        "paystack_test_mode": paystack_is_test_mode(),
        "payment_eligible": order.payment_eligible and not any(p.status == Payment.Status.SUCCESS for p in payments),
        "nav_section": "orders",
    })


@require_POST
def paystack_initialize(request):
    guest_id = _guest_id(request)
    if not guest_id:
        raise Http404("Order not found")

    number = request.POST.get("order_number", "")
    order = get_object_or_404(Order, number=number, guest_id=guest_id)
    order_url = order.get_absolute_url()

    try:
        if not paystack_is_enabled():
            raise PaystackError("Online payment is not configured right now.")
        email = order.customer_email or forms.EmailField().clean(request.POST.get("email", ""))
        validate_order_stock(order)
        payment, should_initialize = create_payment_attempt(order_id=order.pk, email=email)
        if not should_initialize and payment.authorization_url:
            payment = attach_payment_checkout(payment_id=payment.pk)
            return redirect(payment.authorization_url)

        callback_url = request.build_absolute_uri(reverse("orders:paystack_callback"))
        result = initialize_transaction(
            email=payment.customer_email,
            amount=payment.amount,
            reference=payment.reference,
            callback_url=callback_url,
        )
        payment = attach_payment_checkout(payment_id=payment.pk, result=result)
        return redirect(payment.authorization_url)
    except (ValidationError, PaystackError) as error:
        messages.error(request, str(error))
    except ImproperlyConfigured:
        logger.exception("Paystack configuration is invalid.")
        messages.error(request, "Online payment is temporarily unavailable. Please contact CampusFriend.")
    return redirect(order_url)


@require_safe
def paystack_callback(request):
    reference = (request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    trxref = request.GET.get("trxref")
    if not reference or (trxref and request.GET.get("reference") and trxref != reference):
        messages.error(request, "We could not identify this payment.")
        return redirect("orders:order_list")

    payment = get_object_or_404(Payment.objects.select_related("order"), reference=reference)
    guest_id = _guest_id(request)
    if not guest_id or payment.order.guest_id != guest_id:
        raise Http404("Payment not found")

    try:
        result = verify_transaction(payment.reference)
        matched = record_verified_transaction(payment.pk, result)
    except PaystackError:
        messages.error(request, "We could not verify your payment yet. No payment status has been changed.")
        return redirect(payment.order)

    if not matched:
        logger.warning("Paystack verification did not match payment %s.", payment.reference)
        messages.error(request, "The verified payment details did not match this order. No payment was marked as paid.")
    else:
        payment.refresh_from_db()
        if payment.status == Payment.Status.SUCCESS:
            messages.success(request, "Payment received. Your order status will update separately.")
        elif payment.status in {Payment.Status.FAILED, Payment.Status.ABANDONED}:
            messages.error(request, "Payment was not completed. You can try again from this order.")
        else:
            messages.info(request, "Payment is still being confirmed. Refresh this order shortly.")
    return redirect(payment.order)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    try:
        validate_paystack_configuration()
    except PaystackError:
        return HttpResponse(status=503)
    except ImproperlyConfigured:
        logger.exception("Paystack webhook received with invalid configuration.")
        return HttpResponse(status=503)

    payload = request.body
    received_signature = request.headers.get("X-Paystack-Signature", "")
    expected_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha512,
    ).hexdigest()

    if not received_signature or not hmac.compare_digest(received_signature, expected_signature):
        logger.warning("Rejected Paystack webhook with an invalid signature.")
        return HttpResponse(status=401)

    try:
        event = json.loads(payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(event, dict):
        return HttpResponse(status=400)
    if event.get("event") != "charge.success":
        return HttpResponse(status=200)

    data = event.get("data") or {}
    if not isinstance(data, dict):
        return HttpResponse(status=400)

    reference = data.get("reference")
    status = data.get("status")

    if not isinstance(reference, str) or not reference:
        return HttpResponse(status=400)

    if status != "success":
        return HttpResponse(status=400)

    try:
        payment = Payment.objects.select_related("order").get(reference=reference)
    except Payment.DoesNotExist:
        logger.warning("Rejected Paystack webhook with an unknown reference %s.", reference)
        return HttpResponse(status=404)

    if not record_verified_transaction(payment.pk, data):
        logger.warning("Rejected Paystack webhook with mismatched or outdated payment details for %s.", reference)
        return HttpResponse(status=400)
    return HttpResponse(status=200)
