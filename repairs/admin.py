from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError

from .models import (
    PhoneModel,
    PhoneRepairPrice,
    PhoneRepairService,
    RepairNotification,
    RepairPayment,
    RepairNote,
    RepairRequest,
    RepairStatusHistory,
)
from .notifications import retry_notification


@admin.register(PhoneModel)
class PhoneModelAdmin(admin.ModelAdmin):
    list_display = ("brand", "model_name", "phone_type", "active", "created_at")
    list_filter = ("phone_type", "active")
    search_fields = ("brand", "model_name")
    ordering = ("brand", "model_name")


@admin.register(PhoneRepairService)
class PhoneRepairServiceAdmin(admin.ModelAdmin):
    list_display = ("name", "priceable", "active", "slug")
    list_filter = ("priceable", "active")
    search_fields = ("name", "slug")
    ordering = ("name",)


@admin.register(PhoneRepairPrice)
class PhoneRepairPriceAdmin(admin.ModelAdmin):
    list_display = ("service", "phone_model", "price", "active")
    list_filter = ("active", "service", "phone_model__phone_type")
    search_fields = ("service__name", "phone_model__brand", "phone_model__model_name")
    ordering = ("service__name", "phone_model__brand", "phone_model__model_name")


class RepairStatusHistoryInline(admin.TabularInline):
    model = RepairStatusHistory
    extra = 0
    fields = ("status", "note", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class RepairPaymentInline(admin.TabularInline):
    model = RepairPayment
    extra = 0
    can_delete = False
    fields = ("reference", "amount", "currency", "status", "provider", "provider_transaction_id", "paid_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class RepairNoteInline(admin.TabularInline):
    model = RepairNote
    extra = 1
    fields = ("note", "created_at")
    readonly_fields = ("created_at",)
    can_delete = False


class RepairNotificationInline(admin.TabularInline):
    model = RepairNotification
    extra = 0
    can_delete = False
    fields = ("channel", "event", "recipient", "status", "created_at", "sent_at", "error_message")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class RepairRequestAdminForm(forms.ModelForm):
    status_note = forms.CharField(
        label="Status change note",
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Recorded in status history when the status changes.",
    )

    class Meta:
        model = RepairRequest
        fields = "__all__"


@admin.register(RepairRequest)
class RepairRequestAdmin(admin.ModelAdmin):
    form = RepairRequestAdminForm
    list_display = (
        "reference", "customer_name", "phone_number", "service", "phone_model",
        "status", "payment_status", "confirmed_price", "created_at",
    )
    list_filter = ("request_type", "status", "service", "created_at")
    search_fields = (
        "reference", "customer_name", "phone_number", "whatsapp_number", "email",
        "service__name", "phone_model__brand", "phone_model__model_name", "description",
    )
    fieldsets = (
        ("Customer", {"fields": ("customer_name", "phone_number", "whatsapp_number", "email")}),
        ("Repair details", {"fields": (
            "request_type", "service", "phone_type", "phone_model", "confirmed_price",
            "description", "preferred_date", "preferred_time", "image",
        )}),
        ("Operations", {"fields": ("status", "status_note")}),
        ("Record", {"fields": ("reference", "guest_session_id", "created_at", "updated_at")}),
    )
    readonly_fields = ("reference", "guest_session_id", "created_at", "updated_at")
    inlines = [RepairPaymentInline, RepairStatusHistoryInline, RepairNoteInline, RepairNotificationInline]
    ordering = ("-created_at",)
    list_select_related = ("service", "phone_model")

    def get_readonly_fields(self, request, obj=None):
        readonly_fields = list(super().get_readonly_fields(request, obj))
        if obj:
            readonly_fields.extend((
                "request_type", "service", "phone_type", "phone_model", "confirmed_price", "description",
            ))
        return readonly_fields

    @admin.display(description="Payment")
    def payment_status(self, repair_request):
        payment = repair_request.payments.first()
        return payment.get_status_display() if payment else "Not started"

    def save_model(self, request, obj, form, change):
        requested_status = obj.status
        previous_status = form.initial.get("status") if change else None
        if change:
            obj.status = previous_status
        super().save_model(request, obj, form, change)
        if change and requested_status != previous_status:
            try:
                obj.transition_to(
                    requested_status,
                    note=form.cleaned_data.get("status_note", ""),
                )
            except ValidationError:
                raise


@admin.register(RepairStatusHistory)
class RepairStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ("repair_request", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("repair_request__reference", "note")
    ordering = ("-created_at",)


@admin.register(RepairPayment)
class RepairPaymentAdmin(admin.ModelAdmin):
    list_display = ("reference", "repair_request", "amount", "currency", "status", "provider", "created_at")
    list_filter = ("status", "provider", "currency")
    search_fields = ("reference", "repair_request__reference", "provider_transaction_id")
    readonly_fields = tuple(field.name for field in RepairPayment._meta.fields)
    ordering = ("-created_at",)


@admin.register(RepairNotification)
class RepairNotificationAdmin(admin.ModelAdmin):
    list_display = ("repair", "channel", "event", "recipient", "status", "created_at", "sent_at")
    list_filter = ("channel", "status", "event")
    search_fields = ("repair__reference", "recipient", "provider_reference")
    readonly_fields = tuple(field.name for field in RepairNotification._meta.fields)
    ordering = ("-created_at",)
    actions = ("retry_failed_notifications",)

    @admin.action(description="Retry selected failed notifications")
    def retry_failed_notifications(self, request, queryset):
        sent = 0
        failed = 0
        for notification in queryset.filter(status=RepairNotification.Status.FAILED):
            if retry_notification(notification):
                sent += 1
            else:
                failed += 1
        if sent:
            self.message_user(request, f"{sent} notification(s) sent.")
        if failed:
            self.message_user(request, f"{failed} notification(s) still failed.", level="ERROR")
