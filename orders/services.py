"""Explicit, transactional creation of pending guest orders. No stock reservation."""

from decimal import Decimal
import hashlib
import json

from django import forms
from django.core.exceptions import ValidationError
from django.db import IntegrityError, OperationalError, connection, transaction
from django.utils import timezone

from store.catalog import visible_products

from .cart import valid_quantities
from .delivery import DELIVERY_FEES, LOCATION_LABELS
from .models import Order, OrderItem, OrderStatusHistory, Payment
from .payments import generate_payment_reference


class CheckoutError(Exception):
    """An order cannot be placed without the customer reviewing checkout again."""


def delivery_fees():
    return DELIVERY_FEES.copy()


def quote_fingerprint(items, fees):
    # This detects a changed preview; it never supplies prices for an order.
    values = sorted([
        [item["product"].pk, item["quantity"], str(item["product"].price), item["product"].name, item["product"].sku]
        for item in items
    ])
    quotes = sorted((method, str(fee)) for method, fee in fees.items())
    return hashlib.sha256(json.dumps([values, quotes], ensure_ascii=True).encode()).hexdigest()


def create_pending_order(*, guest_id, checkout_token, quantities, expected_fingerprint, customer):
    if not guest_id:
        raise CheckoutError("Please reopen checkout before submitting your order.")
    # A retry returns the original order even after its cart has been cleared.
    existing = Order.objects.filter(guest_id=guest_id, checkout_token=checkout_token).first()
    if existing:
        return existing, False
    cleaned = valid_quantities(quantities)
    if not cleaned or cleaned != quantities:
        raise CheckoutError("Your cart has changed. Please review it before submitting an order.")

    try:
        with transaction.atomic():
            products = list(visible_products().filter(pk__in=cleaned).select_for_update().order_by("pk"))
            if len(products) != len(cleaned):
                raise CheckoutError("Some products are no longer available. Please review your cart.")
            items = []
            for product in products:
                quantity = cleaned[str(product.pk)]
                if not product.is_in_stock or quantity > product.stock:
                    raise CheckoutError(f"The available stock for {product.name} has changed. Please review your cart.")
                items.append({"product": product, "quantity": quantity, "line_total": product.price * quantity})
            fees = delivery_fees()
            area = customer.get("delivery_area")
            if not isinstance(area, str) or area not in fees:
                raise CheckoutError("Select a valid location.")
            method = Order.DeliveryMethod.PICKUP if area == "pickup" else Order.DeliveryMethod.CAMPUS
            fee = fees[area]
            if quote_fingerprint(items, fees) != expected_fingerprint:
                raise CheckoutError("Your cart or prices have changed. Review the updated summary and submit again.")
            subtotal = sum((item["line_total"] for item in items), Decimal("0.00"))
            order = Order(
                guest_id=guest_id, checkout_token=checkout_token,
                customer_name=customer["customer_name"], customer_phone=customer["customer_phone"],
                customer_email=customer["customer_email"], delivery_method=method,
                delivery_area=area, delivery_area_name=LOCATION_LABELS[area],
                delivery_location=customer["delivery_location"],
                landmark=customer["landmark"], delivery_notes=customer["delivery_notes"],
                subtotal=subtotal, delivery_fee=fee,
            )
            order.full_clean(validate_unique=False)
            order.save(force_insert=True)
            OrderStatusHistory.objects.create(order=order, status=order.status)
            snapshots = []
            for item in items:
                product = item["product"]
                snapshot = OrderItem(
                    order=order, product=product, product_name=product.name, sku=product.sku,
                    unit_price=product.price, quantity=item["quantity"], line_total=item["line_total"],
                )
                snapshot.full_clean()
                snapshots.append(snapshot)
            OrderItem.objects.bulk_create(snapshots)
            order = confirm_delivery_quote(order_id=order.pk, fee=fee)
            return order, True
    except IntegrityError:
        # The unique token is also the final guard against concurrent double-submit.
        existing = Order.objects.filter(guest_id=guest_id, checkout_token=checkout_token).first()
        if existing:
            return existing, False
        raise
    except ValidationError as error:
        raise CheckoutError("These order details could not be saved. Check your details and reduce unusually large quantities.") from error
    except OperationalError as error:
        if connection.vendor == "sqlite" and "locked" in str(error).lower():
            raise CheckoutError("Checkout is busy. Please submit again to confirm your request.") from error
        raise


def confirm_delivery_quote(*, order_id, fee):
    """Confirm/update an unpaid quote, preserving snapshots and invalidating old attempts."""
    fee = forms.DecimalField(required=True, max_digits=10, decimal_places=2, min_value=Decimal("0.00")).clean(fee)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if (order.status not in {Order.Status.QUOTE_PENDING, Order.Status.AWAITING_PAYMENT}
                or order.payment_status != Order.PaymentStatus.UNPAID
                or order.payments.filter(status=Payment.Status.SUCCESS).exists()):
            raise ValidationError("This order's quote cannot be changed after payment or fulfilment has progressed.")
        if order.delivery_method == Order.DeliveryMethod.PICKUP and fee != Decimal("0.00"):
            raise ValidationError("Pickup must have a delivery fee of GH₵0.00.")
        if order.delivery_area and fee != order.delivery_fee:
            raise ValidationError("This order has automatic location pricing. Other-location delivery must be arranged separately.")
        previous_fee = order.delivery_fee
        order.delivery_fee = fee
        order.calculate_total()
        order.full_clean()
        # Conditional update also prevents competing confirmations on databases
        # without row-level locks. Payment/fulfilment changes belong to later phases.
        updated = Order.objects.filter(
            pk=order.pk, status=order.status, payment_status=Order.PaymentStatus.UNPAID,
            delivery_fee=previous_fee,
        ).update(delivery_fee=fee, total=order.total, updated_at=timezone.now())
        if not updated:
            raise ValidationError("This order's quote has changed. Reload the order.")
        if previous_fee != fee:
            Payment.invalidate_for_order(order.pk)
        order.set_status(Order.Status.AWAITING_PAYMENT)
        return order


def validate_order_stock(order):
    items = list(order.items.select_related("product"))
    product_ids = [item.product_id for item in items if item.product_id is not None]
    products = {
        product.pk: product
        for product in visible_products().filter(pk__in=product_ids)
    }
    for item in items:
        product = products.get(item.product_id)
        if product is None or not product.is_in_stock or item.quantity > product.stock:
            raise ValidationError(
                f"The available stock for {item.product_name} has changed. Contact CampusFriend before paying."
            )


def create_payment_attempt(*, order_id, email):
    email = forms.EmailField().clean(email)
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.payment_status == Order.PaymentStatus.PAID or order.payments.filter(status=Payment.Status.SUCCESS).exists():
            raise ValidationError("This order has already been paid.")
        if order.status != Order.Status.AWAITING_PAYMENT or order.total is None or order.delivery_fee is None:
            raise ValidationError("Payment is available after CampusFriend confirms the delivery quote.")
        if order.total <= 0:
            raise ValidationError("The order total must be greater than zero before payment.")

        latest = order.payments.first()
        if latest and latest.status == Payment.Status.SUCCESS:
            raise ValidationError("This order has already been paid.")
        if latest and latest.status == Payment.Status.PENDING and latest.invalidated_at is None:
            if latest.amount == order.total and latest.currency == "GHS" and latest.customer_email == email:
                if latest.authorization_url:
                    return latest, False
                return latest, True
            latest.status = Payment.Status.ABANDONED
            latest.save(update_fields={"status", "updated_at"})

        order.customer_email = email
        order.save(update_fields={"customer_email", "updated_at"})
        payment = Payment.objects.create(
            order=order,
            reference=generate_payment_reference(order),
            amount=order.total,
            currency="GHS",
            customer_email=email,
        )
        return payment, True


def attach_payment_checkout(*, payment_id, result=None):
    """Recheck the quote after the provider call before exposing its checkout URL."""
    with transaction.atomic():
        order_id = Payment.objects.values_list("order_id", flat=True).get(pk=payment_id)
        order = Order.objects.select_for_update().get(pk=order_id)
        payment = Payment.objects.select_for_update().get(pk=payment_id)
        if (not order.payment_eligible or payment.invalidated_at is not None
                or payment.status != Payment.Status.PENDING or payment.amount != order.total
                or order.payments.filter(status=Payment.Status.SUCCESS).exists()):
            raise ValidationError("The delivery quote or payment has changed. Review the order before paying.")
        if result is not None:
            payment.authorization_url = result["authorization_url"]
            payment.provider_response = {
                key: result[key] for key in ("reference", "status") if result.get(key) is not None
            }
            payment.save(update_fields={"authorization_url", "provider_response", "updated_at"})
        return payment
