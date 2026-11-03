from decimal import Decimal
import uuid

from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Round
from django.urls import reverse
from django.utils import timezone

from .delivery import LOCATION_CHOICES


def new_order_number():
    return f"CF-{uuid.uuid4().hex[:16].upper()}"


class Order(models.Model):
    class Status(models.TextChoices):
        QUOTE_PENDING = "quote_pending", "Quote pending"
        AWAITING_PAYMENT = "awaiting_payment", "Awaiting payment"
        PAID = "paid", "Paid"
        PROCESSING = "processing", "Processing"
        OUT_FOR_DELIVERY = "out_for_delivery", "Out for delivery"
        DELIVERED = "delivered", "Delivered"

    class PaymentStatus(models.TextChoices):
        UNPAID = "unpaid", "Unpaid"
        PAID = "paid", "Paid"

    class DeliveryMethod(models.TextChoices):
        CAMPUS = "campus", "Campus delivery"
        PICKUP = "pickup", "Pickup"

    number = models.CharField(max_length=19, unique=True, default=new_order_number, editable=False)
    guest_id = models.UUIDField(editable=False, db_index=True)
    checkout_token = models.UUIDField(unique=True, editable=False)
    customer_name = models.CharField(max_length=150)
    customer_phone = models.CharField(max_length=20)
    customer_email = models.EmailField(blank=True)
    delivery_method = models.CharField(max_length=10, choices=DeliveryMethod.choices, default=DeliveryMethod.CAMPUS)
    delivery_area = models.CharField(max_length=20, choices=LOCATION_CHOICES, blank=True, default="")
    delivery_area_name = models.CharField(max_length=150, blank=True, editable=False, verbose_name="Selected location")
    delivery_location = models.CharField(max_length=200, blank=True)
    landmark = models.CharField(max_length=200, blank=True)
    delivery_notes = models.TextField(max_length=1000, blank=True)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    delivery_fee = models.DecimalField(
        max_digits=10, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Delivery included in the online total. For Other location, delivery is agreed and paid separately. Blank denotes a legacy pending quote.",
    )
    total = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True, editable=False)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUOTE_PENDING)
    payment_status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(subtotal__gte=0), name="order_subtotal_nonnegative"),
            models.CheckConstraint(condition=models.Q(delivery_fee__isnull=True) | models.Q(delivery_fee__gte=0), name="order_delivery_fee_nonnegative"),
            models.CheckConstraint(
                condition=~models.Q(delivery_method="pickup") | models.Q(delivery_fee__isnull=False, delivery_fee=0),
                name="order_pickup_has_zero_fee",
            ),
            models.CheckConstraint(
                condition=(models.Q(delivery_fee__isnull=True, total__isnull=True) |
                           models.Q(delivery_fee__isnull=False, total__isnull=False, total=Round(models.F("subtotal") + models.F("delivery_fee"), precision=2))),
                name="order_total_matches_subtotal_fee",
            ),
        ]

    def __str__(self):
        return self.number

    @property
    def status_label(self):
        return self.get_status_display()

    @property
    def payment_status_label(self):
        return self.get_payment_status_display()

    @property
    def status_tone(self):
        return {
            self.Status.QUOTE_PENDING: "pending",
            self.Status.AWAITING_PAYMENT: "pending",
            self.Status.PAID: "confirmed",
            self.Status.PROCESSING: "processing",
            self.Status.OUT_FOR_DELIVERY: "dispatched",
            self.Status.DELIVERED: "delivered",
        }.get(self.status, "neutral")

    def set_status(self, new_status):
        if new_status not in self.Status.values:
            raise ValueError(f"Invalid order status: {new_status}")
        if self.pk is None:
            raise ValueError("Cannot change the status of an unsaved order.")

        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=self.pk)
            if order.status == new_status:
                self.status = order.status
                return False

            order.status = new_status
            order.save(update_fields={"status", "updated_at"})
            OrderStatusHistory.objects.create(order=order, status=new_status)

        self.status = order.status
        self.updated_at = order.updated_at
        return True

    def get_absolute_url(self):
        return reverse("orders:confirmation", args=[self.number])

    def calculate_total(self):
        self.total = None if self.delivery_fee is None else Decimal(self.subtotal) + Decimal(self.delivery_fee)

    @property
    def delivery_fee_separate(self):
        return self.delivery_area == "other"

    @property
    def quote_confirmed(self):
        return (
            self.status in {self.Status.AWAITING_PAYMENT, self.Status.PAID, self.Status.PROCESSING,
                            self.Status.OUT_FOR_DELIVERY, self.Status.DELIVERED}
            and self.delivery_fee is not None and self.total is not None
        )

    @property
    def payment_eligible(self):
        return (
            self.status == self.Status.AWAITING_PAYMENT
            and self.payment_status == self.PaymentStatus.UNPAID
            and self.quote_confirmed and self.total > 0
        )

    def clean(self):
        super().clean()
        # Total is derived, including when validating an Admin/service operation.
        if self.subtotal is not None:
            self.calculate_total()

    def save(self, *args, **kwargs):
        fields = kwargs.get("update_fields")
        # A status/email-only save must not overwrite a newer quote with a stale total.
        if fields is None or {"subtotal", "delivery_fee", "total"}.intersection(fields):
            self.calculate_total()
            if fields is not None:
                kwargs["update_fields"] = set(fields) | {"total"}
        pricing_fields = {"subtotal", "delivery_fee", "delivery_method", "delivery_area", "delivery_area_name"}
        with transaction.atomic():
            changed = False
            if self.pk and (fields is None or pricing_fields.intersection(fields) or "payment_status" in fields):
                original = Order.objects.select_for_update().get(pk=self.pk)
                if (original.payment_status == self.PaymentStatus.PAID
                        and (fields is None or "payment_status" in fields)
                        and self.payment_status != self.PaymentStatus.PAID):
                    raise ValidationError("A paid order cannot be reset to unpaid. Use a separate adjustment workflow.")
                changed = any(
                    getattr(original, field.attname) != getattr(self, field.attname)
                    for field in self._meta.fields
                    if field.name in pricing_fields and (fields is None or field.name in fields or field.attname in fields)
                )
                if changed and (
                    original.payment_status == self.PaymentStatus.PAID
                    or original.payments.filter(status=Payment.Status.SUCCESS).exists()
                ):
                    raise ValidationError("A paid order's delivery and pricing cannot be changed. Use a separate adjustment workflow.")
            result = super().save(*args, **kwargs)
            if changed:
                Payment.invalidate_for_order(self.pk)
            return result


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey("store.Product", on_delete=models.SET_NULL, null=True, blank=True, related_name="order_items")
    product_name = models.CharField(max_length=200)
    sku = models.CharField(max_length=64)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    line_total = models.DecimalField(max_digits=14, decimal_places=2)

    class Meta:
        ordering = ["pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="order_item_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_price__gte=0), name="order_item_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(line_total=Round(models.F("unit_price") * models.F("quantity"), precision=2)), name="order_item_line_total_matches"),
        ]

    def __str__(self):
        return f"{self.quantity} × {self.product_name}"


class OrderStatusHistory(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=20, choices=Order.Status.choices)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "Order status history"
        verbose_name_plural = "Order status histories"

    def __str__(self):
        return f"{self.order.number} — {self.get_status_display()}"


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUCCESS = "success", "Paid"
        FAILED = "failed", "Failed"
        ABANDONED = "abandoned", "Abandoned"

    order = models.ForeignKey(Order, on_delete=models.PROTECT, related_name="payments")
    provider = models.CharField(max_length=30, default="paystack")
    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    currency = models.CharField(max_length=3, default="GHS")
    customer_email = models.EmailField()
    authorization_url = models.URLField(max_length=500, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    provider_transaction_id = models.CharField(max_length=100, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    invalidated_at = models.DateTimeField(null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.order.number} — {self.reference}"

    @classmethod
    def invalidate_for_order(cls, order_id):
        """Called inside the order's pricing transaction; never erase provider history."""
        attempts = cls.objects.filter(order_id=order_id, invalidated_at__isnull=True).exclude(status=cls.Status.SUCCESS)
        attempts.filter(status=cls.Status.PENDING).update(status=cls.Status.ABANDONED)
        attempts.update(invalidated_at=timezone.now(), authorization_url="", updated_at=timezone.now())
