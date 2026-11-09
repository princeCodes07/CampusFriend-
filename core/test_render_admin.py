"""Synthetic admin/readiness tests; no real credentials or owner data are used."""

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import io
import os
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import transaction
from django.test import TestCase, override_settings

from core.catalog_transfer import table_counts
from core.models import BusinessContact
from store.models import Category, Product
from render_admin import create_initial_admin, main, readiness, require_approval
from render_postgres import Refused


class RenderAdminTests(TestCase):
    def setUp(self):
        self.env = {
            "ADMIN_BOOTSTRAP_CONFIRM": "create-initial-admin",
            "ADMIN_BOOTSTRAP_EXPIRES_AT": (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat(),
            "DJANGO_SUPERUSER_USERNAME": "synthetic-owner",
            "DJANGO_SUPERUSER_EMAIL": "owner@example.test",
            "DJANGO_SUPERUSER_PASSWORD": "Synthetic-only-R8!password-47",
        }
        self.User = get_user_model()

    def test_missing_expired_naive_and_excessive_approval_windows_refused(self):
        now = datetime.now(timezone.utc)
        for updates in (
            {"ADMIN_BOOTSTRAP_CONFIRM": ""},
            {"ADMIN_BOOTSTRAP_EXPIRES_AT": "not-a-date"},
            {"ADMIN_BOOTSTRAP_EXPIRES_AT": (now - timedelta(seconds=1)).isoformat()},
            {"ADMIN_BOOTSTRAP_EXPIRES_AT": (now + timedelta(hours=2)).isoformat()},
            {"ADMIN_BOOTSTRAP_EXPIRES_AT": (now + timedelta(minutes=30)).replace(tzinfo=None).isoformat()},
        ):
            with self.subTest(updates=list(updates)), self.assertRaises(Refused):
                require_approval({**self.env, **updates}, now=now)
        require_approval(self.env, now=now)
        self.assertEqual(self.User.objects.count(), 0)

    def test_creates_one_hashed_admin_and_preserves_other_domains(self):
        self.User.objects.create_user(username="existing-customer")
        before = table_counts("default")
        self.assertEqual(create_initial_admin(self.env), "INITIAL_ADMIN_CREATED")
        admin = self.User.objects.get(username=self.env["DJANGO_SUPERUSER_USERNAME"])
        self.assertTrue(admin.is_active and admin.is_staff and admin.is_superuser)
        self.assertTrue(admin.check_password(self.env["DJANGO_SUPERUSER_PASSWORD"]))
        self.assertNotEqual(admin.password, self.env["DJANGO_SUPERUSER_PASSWORD"])
        after = table_counts("default")
        self.assertEqual(after.pop("auth.user"), before.pop("auth.user") + 1)
        self.assertEqual(before, after)

    def test_retry_never_changes_existing_admin_or_password(self):
        create_initial_admin(self.env)
        before = list(self.User.objects.values())
        changed = {**self.env, "DJANGO_SUPERUSER_USERNAME": "another-owner", "DJANGO_SUPERUSER_PASSWORD": "Changed-password-98!"}
        self.assertEqual(create_initial_admin(changed), "EXISTING_SUPERUSER_NO_CHANGES")
        self.assertEqual(list(self.User.objects.values()), before)

    def test_inactive_admin_is_not_reactivated_or_replaced(self):
        self.User.objects.create(username="disabled-owner", is_superuser=True, is_active=False, is_staff=False)
        before = list(self.User.objects.values())
        self.assertEqual(create_initial_admin(self.env), "EXISTING_SUPERUSER_NO_CHANGES")
        self.assertEqual(list(self.User.objects.values()), before)

    def test_username_collision_never_promotes_existing_customer(self):
        user = self.User.objects.create_user(username=self.env["DJANGO_SUPERUSER_USERNAME"].upper())
        with self.assertRaisesRegex(Refused, "EXISTING_USERNAME_REFUSED"):
            create_initial_admin(self.env)
        user.refresh_from_db()
        self.assertFalse(user.is_staff or user.is_superuser)

    def test_email_collision_refused(self):
        self.User.objects.create_user(username="existing", email=self.env["DJANGO_SUPERUSER_EMAIL"].upper())
        with self.assertRaisesRegex(Refused, "EXISTING_EMAIL_REFUSED"):
            create_initial_admin(self.env)
        self.assertEqual(self.User.objects.count(), 1)

    def test_weak_password_rejected_without_creating_account(self):
        with self.assertRaisesRegex(Refused, "ADMIN_PASSWORD_REJECTED"):
            create_initial_admin({**self.env, "DJANGO_SUPERUSER_PASSWORD": "password"})
        self.assertEqual(self.User.objects.count(), 0)

    def test_missing_credentials_and_invalid_email_refused(self):
        for changes in ({"DJANGO_SUPERUSER_PASSWORD": ""}, {"DJANGO_SUPERUSER_EMAIL": "invalid-email"}):
            with self.subTest(changes=list(changes)), self.assertRaises(Refused):
                create_initial_admin({**self.env, **changes})
        self.assertEqual(self.User.objects.count(), 0)

    def test_error_rolls_back_new_admin(self):
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with transaction.atomic():
                create_initial_admin(self.env)
                raise RuntimeError("synthetic")
        self.assertEqual(self.User.objects.count(), 0)

    @override_settings(BUSINESS_PHONE="", WHATSAPP_NUMBER="", BUSINESS_EMAIL="")
    def test_readiness_reports_counts_visibility_and_presence_without_values_or_writes(self):
        category = Category.objects.create(name="Synthetic category")
        Product.objects.create(category=category, name="Visible", sku="VISIBLE", price="10.00", image="products/synthetic.jpg")
        Product.objects.create(category=category, name="Hidden", sku="HIDDEN", price="10.00", is_available=False)
        BusinessContact.objects.create(phone="0300000000", instagram_url="https://example.test/private-social")
        before = table_counts("default")
        report = readiness()
        self.assertEqual(report["product_count"], 2)
        self.assertEqual(report["visible_product_count"], 1)
        self.assertEqual(report["products_with_image_paths"], 1)
        self.assertEqual(report["business_contact_count"], 1)
        self.assertTrue(report["effective_contact_fields_present"]["phone"])
        self.assertTrue(report["social_fields_present"]["instagram_url"])
        self.assertNotIn("0300000000", str(report))
        self.assertNotIn("https://example.test/private-social", str(report))
        self.assertEqual(table_counts("default"), before)

    def test_cli_refuses_creation_before_target_connection_without_approval(self):
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_CONFIRM": ""}), patch("render_admin.validate_target") as target, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["create"]), 1)
        target.assert_not_called()
        self.assertIn("ADMIN_CREATION_NOT_ENABLED", output.getvalue())

    @override_settings(DEBUG=False)
    def test_check_refuses_local_sqlite(self):
        with patch.dict(os.environ, {"RENDER": "true", "DATABASE_URL": "synthetic-placeholder"}), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["check"]), 1)
        self.assertIn("POSTGRESQL_REQUIRED_SQLITE_REFUSED", output.getvalue())

    def test_cli_never_prints_raw_errors_or_credentials(self):
        secret = self.env["DJANGO_SUPERUSER_PASSWORD"]
        with patch("render_admin.run", side_effect=RuntimeError(secret)), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["check"]), 1)
        self.assertNotIn(secret, output.getvalue())
        self.assertEqual(output.getvalue().strip(), "result=FAILED RuntimeError")
