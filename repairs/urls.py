from django.urls import path

from . import views

app_name = "repairs"

urlpatterns = [
    path("", views.home, name="home"),
    path("phone/<slug:service_slug>/", views.phone_repair_service, name="phone_service"),
    path("special/", views.special_phone_request, name="special_phone_request"),
    path("laptop/", views.laptop_request, name="laptop_request"),
    path("electronics/", views.electronics_request, name="electronics_request"),
    path("payments/paystack/initialize/<str:reference>/", views.paystack_initialize, name="paystack_initialize"),
    path("payments/paystack/callback/", views.paystack_callback, name="paystack_callback"),
    path("payments/paystack/webhook/", views.paystack_webhook, name="paystack_webhook"),
    path("<str:reference>/", views.repair_detail, name="repair_detail"),
]
