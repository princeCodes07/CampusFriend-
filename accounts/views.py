"""Customer authentication using Django's password and session protections."""
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_http_methods, require_POST

from orders.cart import CART_SESSION_KEY, Cart


def _safe_next(request):
    destination = request.POST.get("next", request.GET.get("next", ""))
    if not url_has_allowed_host_and_scheme(
        destination, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return ""
    # Authentication endpoints must not redirect to each other in a loop.
    if urlsplit(destination).path in {
        reverse("accounts:login"), reverse("accounts:signup"), reverse("accounts:logout"),
    }:
        return ""
    return destination


class SignInView(LoginView):
    template_name = "accounts/sign_in.html"
    next_page = "core:home"
    redirect_authenticated_user = True
    http_method_names = ["get", "post", "head", "options"]

    def get_redirect_url(self):
        return _safe_next(self.request)


@sensitive_post_parameters("password1", "password2")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def sign_up(request):
    destination = _safe_next(request)
    if request.user.is_authenticated:
        return redirect(destination or "core:home")
    form = UserCreationForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        # Django rotates the session key and retains the visitor's cart.
        login(request, user)
        messages.success(request, "Your account is ready. You're signed in.")
        return redirect(destination or "core:home")
    return render(request, "accounts/sign_up.html", {"form": form, "next": destination})


@never_cache
@csrf_protect
@require_POST
def sign_out(request):
    # Keep only validated shopping quantities. Logout clears authentication,
    # guest order/repair access and checkout tokens from the old session.
    quantities = Cart(request.session).quantities.copy()
    logout(request)
    if quantities:
        request.session[CART_SESSION_KEY] = quantities
    messages.success(request, "You're signed out.")
    return redirect("core:home")
