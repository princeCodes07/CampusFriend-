from django.urls import path

from . import views

app_name = "accounts"
urlpatterns = [
    path("sign-in/", views.SignInView.as_view(), name="login"),
    path("sign-up/", views.sign_up, name="signup"),
    path("sign-out/", views.sign_out, name="logout"),
]
