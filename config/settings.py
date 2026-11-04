"""CampusFriend settings. Export environment variables as described in README.md."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

from .database import database_config

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY.strip():
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY in your environment before running Django. "
        "See README.md for local setup instructions."
    )

DEBUG = os.environ.get("DEBUG", "False").strip().lower() == "true"


def environment_flag(name, default):
    value = os.environ.get(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() == "true"


def environment_integer(name, default):
    value = os.environ.get(name, "").strip()
    if not value:
        return default
    try:
        return int(value)
    except ValueError as error:
        raise ImproperlyConfigured(f"{name} must be an integer.") from error


ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get(
        "ALLOWED_HOSTS", "127.0.0.1,localhost,[::1]" if DEBUG else ""
    ).split(",")
    if host.strip()
]
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

SECURE_SSL_REDIRECT = environment_flag("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = environment_flag("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = environment_flag("CSRF_COOKIE_SECURE", not DEBUG)
SECURE_HSTS_SECONDS = environment_integer("SECURE_HSTS_SECONDS", 0 if DEBUG else 31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = environment_flag("SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = environment_flag("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
secure_proxy_ssl_header = os.environ.get("SECURE_PROXY_SSL_HEADER", "").strip()
if secure_proxy_ssl_header:
    proxy_header_parts = secure_proxy_ssl_header.split(",", 1)
    if len(proxy_header_parts) != 2 or not all(part.strip() for part in proxy_header_parts):
        raise ImproperlyConfigured(
            "SECURE_PROXY_SSL_HEADER must contain a header name and value separated by a comma."
        )
    SECURE_PROXY_SSL_HEADER = tuple(part.strip() for part in proxy_header_parts)
else:
    SECURE_PROXY_SSL_HEADER = None

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
    "accounts",
    "store",
    "orders",
    "repairs",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.business_contact",
                "orders.context_processors.cart_count",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# Exported variables take precedence over .env; blank URL keeps local SQLite.
DATABASES = {"default": database_config(BASE_DIR, os.environ)}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Accra"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# The Books navigation uses this active category, then falls back to the name Books.
BOOKS_CATEGORY_SLUG = "books"

# Owner-supplied public contact details. Empty values are omitted from the footer.
BUSINESS_PHONE = os.environ.get("BUSINESS_PHONE", "").strip()
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "").strip()
BUSINESS_EMAIL = os.environ.get("BUSINESS_EMAIL", "").strip()

# Repairs email notifications remain unsent until host and sender are configured.
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
).strip()
EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()
EMAIL_PORT = environment_integer("EMAIL_PORT", 587)
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "").strip()
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = environment_flag("EMAIL_USE_TLS", True)
EMAIL_USE_SSL = environment_flag("EMAIL_USE_SSL", False)
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "").strip()
EMAIL_TIMEOUT = environment_integer("EMAIL_TIMEOUT", 10)

# Orders delivery locations and fees are fixed in orders/delivery.py.
# Legacy CHECKOUT_DELIVERY_FEE environment values no longer price new orders.

# Paystack hosted checkout. Live keys are blocked unless explicitly authorized.
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "").strip()
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "").strip()
PAYSTACK_BASE_URL = "https://api.paystack.co"
PAYSTACK_CURRENCY = "GHS"
PAYSTACK_LIVE_MODE = os.getenv("PAYSTACK_LIVE_MODE", "False").strip().lower() == "true"
