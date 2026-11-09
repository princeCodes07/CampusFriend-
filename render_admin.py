"""Read-only Render readiness check, or explicitly enabled initial admin setup."""

import argparse
from datetime import datetime, timezone
import json
import os
import sys

from config.safe_logging import exception_summary
from render_postgres import Refused, inspect_database, require, validate_target, verify_server


def require_approval(environ, now=None):
    require(environ.get("ADMIN_BOOTSTRAP_CONFIRM") == "create-initial-admin", "ADMIN_CREATION_NOT_ENABLED")
    try:
        deadline = datetime.fromisoformat(environ.get("ADMIN_BOOTSTRAP_EXPIRES_AT", ""))
    except ValueError:
        raise Refused("INVALID_ADMIN_SETUP_DEADLINE") from None
    require(deadline.tzinfo is not None, "UTC_OFFSET_REQUIRED_IN_DEADLINE")
    remaining = (deadline - (now or datetime.now(timezone.utc))).total_seconds()
    require(0 < remaining <= 3600, "ADMIN_SETUP_WINDOW_EXPIRED_OR_TOO_LONG")


def readiness(using="default"):
    """Counts and presence flags only: never report personal details or secrets."""
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from core.models import BusinessContact
    from store.catalog import visible_products
    from store.models import Category, Product

    users = get_user_model()._default_manager.using(using)
    contacts = BusinessContact.objects.using(using)
    contact = contacts.first()
    details = {field: bool(getattr(settings, setting) or (getattr(contact, field) if contact else ""))
               for field, setting in (("phone", "BUSINESS_PHONE"), ("whatsapp", "WHATSAPP_NUMBER"), ("email", "BUSINESS_EMAIL"))}
    social_fields = ("instagram_url", "tiktok_url", "snapchat_url", "whatsapp_chat_url", "whatsapp_channel_url")
    products = Product.objects.using(using)
    return {
        "category_count": Category.objects.using(using).count(),
        "product_count": products.count(),
        "visible_product_count": visible_products().using(using).count(),
        "products_with_image_paths": products.exclude(image="").count(),
        "business_contact_count": contacts.count(),
        "effective_contact_fields_present": details,
        "social_fields_present": {field: bool(contact and getattr(contact, field)) for field in social_fields},
        "superuser_count": users.filter(is_superuser=True).count(),
        "active_admin_count": users.filter(is_superuser=True, is_staff=True, is_active=True).count(),
    }


def create_initial_admin(environ, using="default"):
    """Called inside the guarded transaction; never updates existing users."""
    from django.contrib.auth import get_user_model, password_validation
    from django.core.exceptions import ValidationError

    require_approval(environ)
    User = get_user_model()
    users = User._default_manager.db_manager(using)
    if users.filter(is_superuser=True).exists():
        return "EXISTING_SUPERUSER_NO_CHANGES"

    username = environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
    email = environ.get("DJANGO_SUPERUSER_EMAIL", "").strip()
    password = environ.get("DJANGO_SUPERUSER_PASSWORD", "")
    require(bool(username and email and password), "PRIVATE_ADMIN_CREDENTIALS_REQUIRED")
    require(not users.filter(username__iexact=username).exists(), "EXISTING_USERNAME_REFUSED")
    require(not users.filter(email__iexact=email).exists(), "EXISTING_EMAIL_REFUSED")
    candidate = User(username=username, email=email, is_superuser=True, is_staff=True, is_active=True)
    try:
        candidate.full_clean(exclude=["password"])
    except ValidationError:
        raise Refused("INVALID_ADMIN_DETAILS") from None
    try:
        password_validation.validate_password(password, candidate)
    except ValidationError:
        raise Refused("ADMIN_PASSWORD_REJECTED") from None
    user = users.create_superuser(username=candidate.username, email=candidate.email, password=password)
    require(user.is_active and user.is_staff and user.is_superuser and user.has_usable_password(), "ADMIN_CREATION_VERIFICATION_FAILED")
    return "INITIAL_ADMIN_CREATED"


def run(mode):
    require(os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings") == "config.settings", "UNEXPECTED_SETTINGS_MODULE")
    if mode == "create":
        require_approval(os.environ)
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
    import django
    django.setup()
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.db import connection, transaction

    validate_target(connection, settings, os.environ)
    try:
        connection.ensure_connection()
        verify_server(connection)
        with transaction.atomic():
            with connection.cursor() as cursor:
                if mode == "check":
                    cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT set_config('lock_timeout', '5000', true)")
                cursor.execute("SELECT set_config('statement_timeout', '60000', true)")
            require(inspect_database(connection) == "CURRENT", "INITIALIZED_SCHEMA_REQUIRED")
            result = "READINESS_CHECK_NO_WRITES"
            if mode == "create":
                # Serialize user writes, including concurrent registration/setup.
                # Reads remain available; lock and statement waits are bounded.
                table = connection.ops.quote_name(get_user_model()._meta.db_table)
                with connection.cursor() as cursor:
                    cursor.execute("LOCK TABLE " + table + " IN SHARE ROW EXCLUSIVE MODE")
                result = create_initial_admin(os.environ)
            report = readiness()
        print(json.dumps({"result": result, **report}, sort_keys=True))
    finally:
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", nargs="?", choices=("check", "create"), default="check")
    args = parser.parse_args(argv)
    try:
        run(args.mode)
    except Exception as error:
        if isinstance(error, Refused):
            reason = error.args[0] if error.args else ""
            if isinstance(reason, str) and reason.replace("_", "").isalnum() and reason.isupper():
                print("result=REFUSED reason=" + reason)
                return 1
        print("result=FAILED " + exception_summary(error))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
