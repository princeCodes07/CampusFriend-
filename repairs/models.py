from decimal import Decimal
import uuid

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.text import slugify


def new_repair_reference():
    return f"RP-{uuid.uuid4().hex[:12].upper()}"


def new_repair_payment_reference():
    return f"{new_repair_reference()}-{uuid.uuid4().hex[:16].upper()}"


class PhoneModel(models.Model):
    class PhoneType(models.TextChoices):
        IPHONE = "IPHONE", "iPhone"
        ANDROID = "ANDROID", "Android"

    brand = models.CharField(max_length=100)
    model_name = models.CharField(max_length=120)
    phone_type = models.CharField(max_length=20, choices=PhoneType.choices)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["brand", "model_name", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["brand", "model_name", "phone_type"],
                name="repairs_phone_model_unique_brand_name_type",
            )
        ]

    def __str__(self):
        return f"{self.get_phone_type_display()} → {self.brand} → {self.model_name}"


class PhoneRepairService(models.Model):
    name = models.CharField(max_length=160, unique=True)
    slug = models.SlugField(max_length=180, unique=True)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    priceable = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name) or "repair-service"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PhoneRepairPrice(models.Model):
    service = models.ForeignKey("PhoneRepairService", on_delete=models.CASCADE, related_name="prices")
    phone_model = models.ForeignKey("PhoneModel", on_delete=models.CASCADE, related_name="repair_prices")
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["service__name", "phone_model__brand", "phone_model__model_name", "pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(price__gt=0), name="repair_price_positive"),
            models.UniqueConstraint(
                fields=["service", "phone_model"],
                condition=models.Q(active=True),
                name="repairs_phone_repair_price_unique_active_service_model",
            ),
        ]

    def clean(self):
        super().clean()
        if self.service_id and not self.service.priceable:
            raise ValidationError({"service": "Only priceable repair services may have a repair price."})

    def __str__(self):
        return f"{self.service.name} + {self.phone_model} = GH₵ {self.price}"


class RepairRequest(models.Model):
    class RequestType(models.TextChoices):
        FIXED_PRICE_PHONE = "FIXED_PRICE_PHONE", "Fixed-price phone repair"
        PHONE_SPECIAL_PROBLEM = "PHONE_SPECIAL_PROBLEM", "Phone special problem"
        LAPTOP = "LAPTOP", "Laptop repair"
        ACCESSORIES_ELECTRONICS = "ACCESSORIES_ELECTRONICS", "Accessories & electronics repair"

    class Status(models.TextChoices):
        REQUESTED = "REQUESTED", "Requested"
        UNDER_REVIEW = "UNDER_REVIEW", "Under review"
        CONTACTED = "CONTACTED", "Contacted"
        PRICE_CONFIRMED = "PRICE_CONFIRMED", "Price confirmed"
        PAYMENT_PENDING = "PAYMENT_PENDING", "Payment pending"
        PAID = "PAID", "Paid"
        REPAIR_IN_PROGRESS = "REPAIR_IN_PROGRESS", "Repair in progress"
        READY = "READY", "Ready"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    reference = models.CharField(max_length=30, unique=True, editable=False, default=new_repair_reference)
    request_type = models.CharField(max_length=30, choices=RequestType.choices)
    customer_name = models.CharField(max_length=150, blank=True)
    phone_number = models.CharField(max_length=20, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    description = models.TextField(blank=True)
    preferred_date = models.DateField(null=True, blank=True)
    preferred_time = models.TimeField(null=True, blank=True)
    image = models.ImageField(upload_to="repairs/%Y/%m/", blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.REQUESTED)
    guest_session_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text="Guest or session identifier used to keep requests anonymous and session-based.",
    )
    phone_type = models.CharField(max_length=20, choices=PhoneModel.PhoneType.choices, blank=True)
    service = models.ForeignKey(
        "PhoneRepairService",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_requests",
    )
    phone_model = models.ForeignKey(
        "PhoneModel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="repair_requests",
    )
    confirmed_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]

    def validate_status_transition(self, new_status, current_status=None):
        if new_status not in self.Status.values:
            raise ValidationError({"status": f"Invalid repair status: {new_status}"})

        current_status = current_status or self.status
        if new_status == current_status:
            return

        transitions = {
            self.Status.REQUESTED: {self.Status.UNDER_REVIEW, self.Status.CANCELLED},
            self.Status.UNDER_REVIEW: {self.Status.CONTACTED, self.Status.CANCELLED},
            self.Status.CONTACTED: {
                self.Status.PRICE_CONFIRMED,
                self.Status.REPAIR_IN_PROGRESS,
                self.Status.CANCELLED,
            },
            self.Status.PRICE_CONFIRMED: {self.Status.REPAIR_IN_PROGRESS, self.Status.CANCELLED},
            self.Status.PAYMENT_PENDING: {self.Status.PRICE_CONFIRMED, self.Status.PAID, self.Status.CANCELLED},
            self.Status.PAID: {self.Status.REPAIR_IN_PROGRESS},
            self.Status.REPAIR_IN_PROGRESS: {self.Status.READY},
            self.Status.READY: {self.Status.COMPLETED},
            self.Status.COMPLETED: set(),
            self.Status.CANCELLED: set(),
        }
        allowed = transitions.get(current_status, set())
        is_fixed_price = self.request_type == self.RequestType.FIXED_PRICE_PHONE
        if is_fixed_price:
            if current_status == self.Status.PRICE_CONFIRMED:
                allowed = {self.Status.PAYMENT_PENDING, self.Status.CANCELLED}
            elif current_status == self.Status.PAYMENT_PENDING:
                allowed = {self.Status.PRICE_CONFIRMED, self.Status.PAID, self.Status.CANCELLED}
        elif new_status in {self.Status.PAYMENT_PENDING, self.Status.PAID}:
            allowed = set()

        if new_status not in allowed:
            raise ValidationError({
                "status": f"A repair cannot move from {self.get_status_display()} to {self.Status(new_status).label}."
            })

        if is_fixed_price and new_status == self.Status.PAYMENT_PENDING:
            matching_attempt = self.payments.filter(
                status=RepairPayment.Status.PENDING,
                amount=self.confirmed_price,
            ).exists()
            if not matching_attempt:
                raise ValidationError({"status": "A matching pending payment attempt is required."})

        if is_fixed_price and new_status == self.Status.PAID:
            matching_payment = self.payments.filter(
                status=RepairPayment.Status.PAID,
                amount=self.confirmed_price,
            ).exists()
            if not matching_payment:
                raise ValidationError({"status": "A matching successful payment is required."})

        if (
            is_fixed_price
            and current_status == self.Status.PAYMENT_PENDING
            and new_status in {self.Status.PRICE_CONFIRMED, self.Status.CANCELLED}
            and self.payments.filter(status=RepairPayment.Status.PENDING).exists()
        ):
            raise ValidationError({"status": "A pending payment attempt must resolve before changing this repair."})

    def transition_to(self, new_status, note=""):
        if self.pk is None:
            raise ValidationError("An unsaved repair cannot change status.")

        with transaction.atomic():
            repair_request = type(self).objects.select_for_update().get(pk=self.pk)
            if new_status == repair_request.status:
                self.status = repair_request.status
                return False
            repair_request.validate_status_transition(new_status)
            changed_at = timezone.now()
            type(self).objects.filter(pk=self.pk).update(
                status=new_status,
                updated_at=changed_at,
            )
            RepairStatusHistory.objects.create(
                repair_request=repair_request,
                status=new_status,
                note=note,
                created_at=changed_at,
            )

        self.status = new_status
        self.updated_at = changed_at
        from .notifications import create_notification_for_status

        create_notification_for_status(self)
        return True

    def clean(self):
        super().clean()
        if self.pk:
            current_status = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if current_status and current_status != self.status:
                self.validate_status_transition(self.status, current_status=current_status)
        elif self.status not in {self.Status.REQUESTED, self.Status.PRICE_CONFIRMED}:
            raise ValidationError({"status": "A new repair must start as requested or price confirmed."})

    def save(self, *args, **kwargs):
        if not self.reference:
            self.reference = new_repair_reference()
        update_fields = kwargs.get("update_fields")
        writes_status = update_fields is None or "status" in update_fields
        if self.pk and writes_status:
            stored_status = type(self).objects.filter(pk=self.pk).values_list("status", flat=True).first()
            if stored_status is not None and stored_status != self.status:
                raise ValidationError({"status": "Use transition_to() to change a repair status."})
        if self.pk is None and self.status not in {self.Status.REQUESTED, self.Status.PRICE_CONFIRMED}:
            raise ValidationError({"status": "A new repair must start as requested or price confirmed."})
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference} — {self.get_request_type_display()}"


class RepairStatusHistory(models.Model):
    repair_request = models.ForeignKey("RepairRequest", on_delete=models.CASCADE, related_name="status_history")
    status = models.CharField(max_length=30, choices=RepairRequest.Status.choices)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "Repair status history"
        verbose_name_plural = "Repair status histories"

    def __str__(self):
        return f"{self.repair_request.reference} — {self.get_status_display()}"


class RepairNote(models.Model):
    repair_request = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="internal_notes",
    )
    note = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        verbose_name = "Internal repair note"
        verbose_name_plural = "Internal repair notes"

    def __str__(self):
        return f"Internal note for {self.repair_request.reference}"


class RepairNotification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        SMS = "SMS", "SMS"
        WHATSAPP = "WHATSAPP", "WhatsApp"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        SENT = "SENT", "Sent"
        FAILED = "FAILED", "Failed"

    repair = models.ForeignKey(
        RepairRequest,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    channel = models.CharField(max_length=20, choices=Channel.choices)
    event = models.CharField(max_length=80)
    recipient = models.CharField(max_length=255)
    subject = models.CharField(max_length=255, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider_reference = models.CharField(max_length=255, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["repair", "channel", "event"],
                name="unique_repair_notification_event_channel",
            ),
        ]

    def __str__(self):
        return f"{self.repair.reference} — {self.get_channel_display()} — {self.event}"


class RepairPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Payment pending"
        PAID = "PAID", "Paid"
        FAILED = "FAILED", "Failed"
        ABANDONED = "ABANDONED", "Abandoned"

    repair_request = models.ForeignKey(
        RepairRequest,
        on_delete=models.PROTECT,
        related_name="payments",
    )
    reference = models.CharField(
        max_length=100,
        unique=True,
        default=new_repair_payment_reference,
        editable=False,
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    provider = models.CharField(max_length=30, default="paystack")
    provider_transaction_id = models.CharField(max_length=100, blank=True)
    authorization_url = models.URLField(max_length=500, blank=True)
    provider_response = models.JSONField(default=dict, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="repair_payment_amount_positive"),
        ]

    def __str__(self):
        return f"{self.repair_request.reference} — {self.reference}"
