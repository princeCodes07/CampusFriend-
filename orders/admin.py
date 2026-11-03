from django.contrib import admin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.views.decorators.http import require_http_methods

from .forms import DeliveryQuoteForm
from .models import Order, OrderItem, OrderStatusHistory, Payment
from .services import confirm_delivery_quote


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    fields = ("product_name", "sku", "unit_price", "quantity", "line_total")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class OrderStatusHistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    fields = ("status", "created_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    fields = ("reference", "status", "amount", "currency", "customer_email", "created_at", "paid_at", "invalidated_at")
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    change_form_template = "admin/orders/order/change_form.html"
    view_on_site = False  # Guest confirmation requires the customer's session.
    list_display = ("number", "customer_name", "customer_phone", "delivery_area_name", "delivery_fee_separate", "subtotal", "delivery_fee", "total", "status", "payment_status", "created_at")
    search_fields = ("number", "customer_name", "customer_phone", "customer_email", "delivery_location")
    list_filter = ("status", "payment_status", "delivery_area", "created_at")
    date_hierarchy = "created_at"
    fields = ("number", "status", "payment_status", "customer_name", "customer_phone", "customer_email",
              "delivery_method", "delivery_area", "delivery_area_name", "delivery_fee_separate", "delivery_location", "landmark", "delivery_notes", "subtotal", "delivery_fee", "total", "created_at", "updated_at")
    readonly_fields = fields
    inlines = (OrderItemInline, OrderStatusHistoryInline, PaymentInline)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def can_confirm_quote(self, request, obj):
        return (obj is not None and request.user.has_perm("orders.change_order")
                and not obj.delivery_area
                and obj.status in {Order.Status.QUOTE_PENDING, Order.Status.AWAITING_PAYMENT}
                and obj.payment_status == Order.PaymentStatus.UNPAID
                and not obj.payments.filter(status=Payment.Status.SUCCESS).exists())

    def render_change_form(self, request, context, *args, **kwargs):
        obj = kwargs.get("obj")
        context["can_confirm_quote"] = self.can_confirm_quote(request, obj)
        return super().render_change_form(request, context, *args, **kwargs)

    def get_urls(self):
        quote_view = require_http_methods(["GET", "POST"])(self.confirm_quote_view)
        return [path("<int:object_id>/quote/", self.admin_site.admin_view(quote_view), name="orders_order_quote")] + super().get_urls()

    def confirm_quote_view(self, request, object_id):
        if not request.user.has_perm("orders.change_order"):
            raise PermissionDenied
        order = self.get_object(request, object_id)
        if order is None:
            raise Http404("Order not found")
        change_url = reverse("admin:orders_order_change", args=[order.pk])
        if not self.can_confirm_quote(request, order):
            self.message_user(request, "This quote cannot be changed after payment or fulfilment has progressed.", level="WARNING")
            return redirect(change_url)
        form = DeliveryQuoteForm(request.POST if request.method == "POST" else None, initial={"delivery_fee": order.delivery_fee})
        if request.method == "POST" and form.is_valid():
            try:
                order = confirm_delivery_quote(order_id=order.pk, fee=form.cleaned_data["delivery_fee"])
            except ValidationError as error:
                form.add_error(None, error)
            else:
                self.log_change(request, order, f"Confirmed delivery fee GHS {order.delivery_fee:.2f}; total GHS {order.total:.2f}. Any attempts for a changed fee were invalidated.")
                self.message_user(request, "Delivery quote confirmed. The final total was calculated and the order is awaiting payment. No payment was recorded.")
                return redirect(change_url)
        return TemplateResponse(request, "admin/orders/order/quote.html", {
            **self.admin_site.each_context(request), "title": f"Confirm delivery quote: {order.number}",
            "opts": self.model._meta, "order": order, "form": form, "change_url": change_url,
        })
