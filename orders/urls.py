from django.urls import path

from . import views


app_name = "orders"
urlpatterns = [
    path("cart/", views.cart_detail, name="cart_detail"),
    path("cart/add/<int:product_id>/", views.cart_add, name="cart_add"),
    path("cart/remove/<int:product_id>/", views.cart_remove, name="cart_remove"),
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_list, name="order_list"),
    # Preserve old bookmarks; the guest order list is the canonical tracking entry.
    path("track/", views.track, name="track"),
    path("orders/<str:number>/", views.confirmation, name="confirmation"),
    path("payments/paystack/initialize/", views.paystack_initialize, name="paystack_initialize"),
    path("payments/paystack/callback/", views.paystack_callback, name="paystack_callback"),
    path("orders/payments/paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
]
