"""Fixed delivery locations and payment safety; provider calls are always mocked."""
from decimal import Decimal
import hashlib
import hmac
import json
import uuid
from unittest.mock import Mock, patch

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from store.models import Category, Product
from .cart import CART_SESSION_KEY
from .delivery import DELIVERY_FEES
from .forms import CheckoutForm
from .models import Order, Payment
from .payments import record_verified_transaction
from .services import CheckoutError, confirm_delivery_quote, create_payment_attempt, create_pending_order
from .views import GUEST_SESSION_KEY, PREVIEW_SESSION_KEY


@override_settings(
    PAYSTACK_PUBLIC_KEY="pk_test_example", PAYSTACK_SECRET_KEY="sk_test_example", PAYSTACK_LIVE_MODE=False,
    SECURE_SSL_REDIRECT=False,
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class FixedLocationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        category = Category.objects.create(name="Delivery test products")
        cls.product = Product.objects.create(category=category, name="Test item", sku="DELIVERY-TEST", price="22.74", stock=5)

    def prepare(self, **changes):
        self.client.post(reverse("orders:cart_add", args=[self.product.pk]), {"quantity": 2})
        response = self.client.get(reverse("orders:checkout"))
        return {
            "checkout_token": response.context["form"]["checkout_token"].value(),
            "customer_name": "Delivery Test", "customer_phone": "0240000000",
            "customer_email": "delivery@example.test", "delivery_area": "campus",
            "delivery_location": "Fixture address, room 12", "landmark": "Fixture entrance",
            "delivery_notes": "Test only", **changes,
        }

    def place(self, **changes):
        data = self.prepare(**changes)
        response = self.client.post(reverse("orders:checkout"), data)
        self.assertEqual(response.status_code, 302)
        return Order.objects.get(checkout_token=data["checkout_token"])

    def legacy(self):
        # Explicit fixture for an order saved before automatic location pricing.
        order = self.place()
        Order.objects.filter(pk=order.pk).update(delivery_area="", delivery_area_name="", delivery_fee=None,
                                                total=None, status="quote_pending")
        order.status_history.exclude(status="quote_pending").delete()
        return confirm_delivery_quote(order_id=order.pk, fee="10.00")

    def payment(self, order):
        return create_payment_attempt(order_id=order.pk, email=order.customer_email)[0]

    def verified_data(self, payment, **changes):
        return {"reference": payment.reference, "status": "success", "amount": int(payment.amount * 100),
                "currency": "GHS", "id": 12345, **changes}

    def webhook(self, payment, **changes):
        payload = json.dumps({"event": "charge.success", "data": self.verified_data(payment, **changes)}).encode()
        signature = hmac.new(settings.PAYSTACK_SECRET_KEY.encode(), payload, hashlib.sha512).hexdigest()
        return self.client.post(reverse("orders:paystack_webhook"), payload, content_type="application/json",
                                HTTP_X_PAYSTACK_SIGNATURE=signature)

    def test_exact_location_selector_replaces_zone_and_method_selectors(self):
        self.prepare()
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(list(response.context["form"].fields["delivery_area"].choices), [
            ("", "Select location"), ("campus", "Campus"), ("pickup", "Pickup (Palms Eatery)"),
            ("ayeduase", "Ayeduase"), ("kotei", "Kotei"), ("boadi", "Boadi"),
            ("newsite", "Newsite"), ("other", "Other location"),
        ])
        self.assertNotContains(response, 'name="delivery_zone"')
        self.assertNotContains(response, 'name="delivery_method"')
        self.assertNotContains(response, "manual quote")
        self.assertContains(response, 'name="delivery_location"')
        self.assertContains(response, 'name="landmark"')
        self.assertNotIn("DeliveryZone", [model.__name__ for model in admin.site._registry])

    def test_checkout_starts_with_one_summary_and_no_assumed_delivery_price(self):
        self.prepare()
        response = self.client.get(reverse("orders:checkout"))
        self.assertContains(response, 'id="delivery-summary"', count=1)
        self.assertNotContains(response, 'data-delivery-quote=')
        summary = response.content.decode().split('id="delivery-summary"')[1].split("</section>")[0]
        self.assertIn("Select your location", summary)
        self.assertIn("GH₵ 45.48", summary)
        self.assertNotIn("GH₵ 10.00", summary)
        self.assertNotIn("GH₵ 55.48", summary)
        self.assertFalse(Order.objects.exists())

    def test_validation_errors_keep_only_selected_location_in_summary(self):
        data = self.prepare(customer_name="")
        labels = dict(CheckoutForm.base_fields["delivery_area"].choices)
        for area, fee in DELIVERY_FEES.items():
            with self.subTest(area=area):
                response = self.client.post(reverse("orders:checkout"), {**data, "delivery_area": area})
                self.assertContains(response, 'id="delivery-summary"', count=1)
                summary = response.content.decode().split('id="delivery-summary"')[1].split("</section>")[0]
                self.assertIn(labels[area], summary)
                self.assertIn(f"GH₵ {Decimal('45.48') + fee:.2f}", summary)
                for other_area, label in labels.items():
                    if other_area and other_area != area:
                        self.assertNotIn(f">{label}</h3>", summary)
                if area == "other":
                    self.assertIn('id="delivery-summary-fee-row" hidden', summary)
                    self.assertIn("Delivery is not included", summary)
        self.assertFalse(Order.objects.exists())

    def test_payment_summary_precedes_status_tracking_and_items(self):
        order = self.place(delivery_area="ayeduase")
        for pending_attempt in (False, True):
            with self.subTest(pending_attempt=pending_attempt):
                if pending_attempt:
                    self.payment(order)
                html = self.client.get(order.get_absolute_url()).content.decode()
                action = html.index('action="' + reverse("orders:paystack_initialize") + '"')
                self.assertLess(html.index('id="saved-summary-title"'), action)
                for heading in ("order-status-title", "payment-status-title", "order-tracking-title", "saved-items-title"):
                    self.assertLess(action, html.index(f'id="{heading}"'))

    @patch("orders.payments.requests.post")
    def test_every_location_is_automatically_payable_for_correct_server_total(self, post):
        expected_fees = {"campus": "0.00", "pickup": "0.00", "ayeduase": "10.00", "kotei": "10.00",
                         "boadi": "10.00", "newsite": "10.00", "other": "0.00"}
        for area, fee in expected_fees.items():
            with self.subTest(area=area):
                order = self.place(delivery_area=area, delivery_fee="0", total="0", status="paid")
                self.assertEqual(order.delivery_fee, Decimal(fee))
                self.assertEqual(order.total, Decimal("45.48") + Decimal(fee))
                self.assertTrue(order.payment_eligible)
                self.assertEqual(order.payment_status, "unpaid")
                self.assertEqual(list(order.status_history.values_list("status", flat=True)), ["quote_pending", "awaiting_payment"])
                response = Mock()
                response.json.side_effect = lambda: {"status": True, "data": {
                    "reference": order.payments.first().reference, "authorization_url": "https://checkout.paystack.com/test",
                }}
                post.return_value = response
                result = self.client.post(reverse("orders:paystack_initialize"), {"order_number": order.number, "amount": "1"})
                self.assertRedirects(result, "https://checkout.paystack.com/test", fetch_redirect_response=False)
                self.assertEqual(post.call_args.kwargs["json"]["amount"], int(order.total * 100))
                self.assertEqual(self.webhook(order.payments.first()).status_code, 200)
                order.refresh_from_db()
                self.assertEqual(order.payment_status, "paid")
                self.assertEqual(order.status, "awaiting_payment")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 5)

    def test_other_location_excludes_delivery_price_and_remains_clear_after_payment(self):
        order = self.place(delivery_area="other")
        self.assertTrue(order.delivery_fee_separate)
        self.assertEqual(order.total, order.subtotal)
        page = self.client.get(order.get_absolute_url())
        self.assertContains(page, "Items total (delivery separate)")
        self.assertNotContains(page, "<dt>Delivery</dt>", html=True)
        self.assertNotContains(page, "To be confirmed")
        self.assertContains(page, "Delivery is not included in this payment.")
        self.assertContains(page, reverse("orders:paystack_initialize"))
        self.webhook(self.payment(order))
        paid_page = self.client.get(order.get_absolute_url())
        self.assertContains(paid_page, "Payment received")
        self.assertContains(paid_page, "Delivery is not included in this payment.")
        self.assertNotContains(paid_page, reverse("orders:paystack_initialize"))
        self.assertContains(self.client.get(reverse("orders:order_list")), "Delivery separate")

    def test_pickup_needs_no_address_and_names_palms_eatery(self):
        order = self.place(delivery_area="pickup", delivery_location="", landmark="")
        self.assertEqual(order.delivery_method, "pickup")
        self.assertEqual(order.delivery_area_name, "Pickup (Palms Eatery)")
        self.assertEqual(order.delivery_fee, Decimal("0.00"))
        self.assertContains(self.client.get(order.get_absolute_url()), "Palms Eatery")

    def test_all_deliveries_require_address_and_landmark(self):
        data = self.prepare()
        for area in ("campus", "ayeduase", "kotei", "boadi", "newsite", "other"):
            response = self.client.post(reverse("orders:checkout"), {**data, "delivery_area": area, "delivery_location": "", "landmark": ""})
            self.assertIn("delivery_location", response.context["form"].errors)
            self.assertIn("landmark", response.context["form"].errors)
        self.assertFalse(Order.objects.exists())

    def test_invalid_location_is_rejected_even_with_forged_legacy_fields(self):
        data = self.prepare()
        for area in ("", "fake", "1", "-1", "CAMPUS", "9" * 100):
            response = self.client.post(reverse("orders:checkout"), {**data, "delivery_area": area,
                "delivery_zone": "other", "delivery_method": "pickup", "delivery_fee": "0"})
            self.assertIn("delivery_area", response.context["form"].errors)
        self.assertFalse(Order.objects.exists())
        self.assertIn(CART_SESSION_KEY, self.client.session)

    def test_service_rejects_missing_or_unknown_location(self):
        data = self.prepare()
        session = self.client.session
        for area in (None, "forged", {}):
            with self.subTest(area=area), self.assertRaises(CheckoutError):
                create_pending_order(guest_id=session[GUEST_SESSION_KEY], checkout_token=data["checkout_token"],
                    quantities=session[CART_SESSION_KEY], expected_fingerprint=session[PREVIEW_SESSION_KEY]["fingerprint"],
                    customer={**data, "delivery_area": area})
        self.assertFalse(Order.objects.exists())

    @override_settings(CHECKOUT_DELIVERY_FEE="999.00")
    def test_posted_fees_methods_and_legacy_environment_do_not_override_fixed_fee(self):
        order = self.place(delivery_area="kotei", delivery_method="pickup", delivery_fee="0", delivery_zone="other", total="0")
        self.assertEqual(order.delivery_method, "campus")
        self.assertEqual(order.delivery_fee, Decimal("10.00"))
        self.assertEqual(order.total, Decimal("55.48"))

    def test_saved_location_fee_is_a_snapshot_and_policy_change_requires_preview_review(self):
        order = self.place(delivery_area="ayeduase")
        data = self.prepare(delivery_area="ayeduase")
        with patch.dict(DELIVERY_FEES, {"ayeduase": Decimal("12.00")}):
            response = self.client.post(reverse("orders:checkout"), data)
            self.assertContains(response, "Your cart or prices have changed.")
            self.assertEqual(Order.objects.count(), 1)
            data["checkout_token"] = response.context["form"]["checkout_token"].value()
            self.client.post(reverse("orders:checkout"), data)
            self.assertEqual(Order.objects.get(checkout_token=data["checkout_token"]).delivery_fee, Decimal("12.00"))
        order.refresh_from_db()
        self.assertEqual(order.delivery_fee, Decimal("10.00"))

    def test_automatic_order_has_no_admin_quote_action_and_ownership_remains_private(self):
        order = self.place(delivery_area="other")
        browser = Client()
        browser.force_login(get_user_model().objects.create_superuser(username="delivery-admin", password=None))
        quote_url = reverse("admin:orders_order_quote", args=[order.pk])
        self.assertNotContains(browser.get(reverse("admin:orders_order_change", args=[order.pk])), quote_url)
        browser.post(quote_url, {"delivery_fee": "10.00"})
        with self.assertRaises(ValidationError):
            confirm_delivery_quote(order_id=order.pk, fee="10.00")
        order.refresh_from_db()
        self.assertEqual(order.total, order.subtotal)
        self.assertEqual(Client().get(order.get_absolute_url()).status_code, 404)

    def test_same_fee_reconfirmation_preserves_attempt_and_history(self):
        order = self.place()
        payment = self.payment(order)
        confirm_delivery_quote(order_id=order.pk, fee="0.00")
        payment.refresh_from_db()
        self.assertIsNone(payment.invalidated_at)
        self.assertEqual(order.status_history.count(), 2)
        self.assertEqual(self.payment(order).pk, payment.pk)

    def test_legacy_quote_updates_invalidate_all_old_references_even_if_fee_reverts(self):
        order = self.legacy()
        old = self.payment(order)
        old.authorization_url = "https://checkout.paystack.com/old"
        old.save()
        failed = Payment.objects.create(order=order, reference="failed-test", amount=order.total, customer_email=order.customer_email, status="failed")
        confirm_delivery_quote(order_id=order.pk, fee="8.00")
        confirm_delivery_quote(order_id=order.pk, fee="10.00")
        for attempt in (old, failed):
            attempt.refresh_from_db()
            self.assertIsNotNone(attempt.invalidated_at)
            self.assertEqual(attempt.authorization_url, "")
            self.assertFalse(record_verified_transaction(attempt.pk, self.verified_data(attempt)))
        self.assertEqual(old.status, "abandoned")
        self.assertEqual(failed.status, "failed")
        fresh = self.payment(order)
        self.assertNotIn(fresh.reference, {old.reference, failed.reference})
        self.assertTrue(record_verified_transaction(fresh.pk, self.verified_data(fresh)))

    @patch("orders.payments.requests.get")
    def test_stale_callback_and_webhook_cannot_mark_repriced_legacy_order_paid(self, get):
        order = self.legacy()
        payment = self.payment(order)
        confirm_delivery_quote(order_id=order.pk, fee="8.00")
        get.return_value = Mock()
        get.return_value.json.return_value = {"status": True, "data": self.verified_data(payment)}
        self.client.get(reverse("orders:paystack_callback"), {"reference": payment.reference})
        self.assertEqual(self.webhook(payment).status_code, 400)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "unpaid")
        self.assertEqual(order.total, Decimal("53.48"))

    @patch("orders.payments.requests.post")
    def test_quote_change_during_initialization_does_not_publish_stale_checkout(self, post):
        order = self.legacy()
        def initialize(*args, **kwargs):
            confirm_delivery_quote(order_id=order.pk, fee="8.00")
            response = Mock()
            response.json.return_value = {"status": True, "data": {"reference": kwargs["json"]["reference"], "authorization_url": "https://checkout.paystack.com/stale"}}
            return response
        post.side_effect = initialize
        response = self.client.post(reverse("orders:paystack_initialize"), {"order_number": order.number})
        self.assertRedirects(response, order.get_absolute_url())
        self.assertEqual(Payment.objects.get().authorization_url, "")

    def test_paid_order_rejects_pricing_location_and_payment_flag_changes(self):
        order = self.place()
        self.webhook(self.payment(order))
        for field, value in (("delivery_fee", Decimal("10.00")), ("subtotal", Decimal("1.00")),
                             ("delivery_area", "other"), ("delivery_area_name", "Other location"), ("payment_status", "unpaid")):
            order.refresh_from_db()
            setattr(order, field, value)
            with self.subTest(field=field), self.assertRaises(ValidationError):
                order.save(update_fields=[field])
        with self.assertRaises(ValidationError):
            confirm_delivery_quote(order_id=order.pk, fee="10.00")
        order.refresh_from_db()
        self.assertEqual(order.payment_status, "paid")
        self.assertEqual(order.delivery_area, "campus")

    def test_stale_full_save_cannot_reset_paid_order(self):
        order = self.place()
        self.webhook(self.payment(order))
        with self.assertRaises(ValidationError):
            order.save()

    def test_duplicate_success_preserves_fulfilment_and_payment_timestamp(self):
        order = self.place()
        payment = self.payment(order)
        self.webhook(payment)
        payment.refresh_from_db()
        paid_at = payment.paid_at
        order.set_status(Order.Status.PROCESSING)
        self.assertEqual(self.webhook(payment).status_code, 200)
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.paid_at, paid_at)
        self.assertEqual(order.status, "processing")

    def test_legacy_model_fee_save_invalidates_attempt_and_stale_email_save_preserves_total(self):
        order = self.legacy()
        stale = Order.objects.get(pk=order.pk)
        payment = self.payment(order)
        order.delivery_fee = Decimal("8.00")
        order.save(update_fields=["delivery_fee"])
        payment.refresh_from_db()
        self.assertIsNotNone(payment.invalidated_at)
        stale.customer_email = "updated@example.test"
        stale.save(update_fields=["customer_email"])
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("53.48"))

    def test_legacy_quote_update_rolls_back_if_invalidation_fails(self):
        order = self.legacy()
        with patch("orders.services.Payment.invalidate_for_order", side_effect=RuntimeError("invalidation failed")):
            with self.assertRaises(RuntimeError):
                confirm_delivery_quote(order_id=order.pk, fee="8.00")
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("55.48"))

    def test_webhook_rejects_malformed_amounts_without_server_error(self):
        payment = self.payment(self.place())
        for amount in ("bad", "4548", 4548.0, None, True, [], {}):
            with self.subTest(amount=amount):
                self.assertEqual(self.webhook(payment, amount=amount).status_code, 400)


class FixedLocationMigrationTests(TransactionTestCase):
    def test_zone_removal_preserves_historical_names_fees_payments_and_addresses(self):
        previous = [("orders", "0004_delivery_pricing_v1")]
        current = [("orders", "0005_fixed_delivery_locations")]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate(previous)
            old_apps = executor.loader.project_state(previous).apps
            LegacyOrder = old_apps.get_model("orders", "Order")
            LegacyPayment = old_apps.get_model("orders", "Payment")
            zone = old_apps.get_model("orders", "DeliveryZone").objects.create(name="Historical fixture", fee="5.00")
            for suffix, paid, fee, total in (("PAID", True, Decimal("5.00"), Decimal("25.00")),
                                             ("PENDING", False, None, None)):
                order = LegacyOrder.objects.create(
                    number="CF-MIGRATE-" + suffix, guest_id=uuid.uuid4(), checkout_token=uuid.uuid4(),
                    customer_name="Migration fixture", customer_phone="0240000000", delivery_zone=zone,
                    delivery_zone_name="Original name" if paid else "", delivery_location="Legacy address", landmark="Legacy landmark", subtotal="20.00",
                    delivery_fee=fee, total=total, payment_status="paid" if paid else "unpaid",
                    status="processing" if paid else "quote_pending",
                )
                if paid:
                    LegacyPayment.objects.create(order=order, reference="migration-paid", status="success",
                                                 amount=total, customer_email="migration@example.test")
            executor = MigrationExecutor(connection)
            executor.migrate(current)
            new_apps = executor.loader.project_state(current).apps
            NewOrder = new_apps.get_model("orders", "Order")
            paid = NewOrder.objects.get(number="CF-MIGRATE-PAID")
            pending = NewOrder.objects.get(number="CF-MIGRATE-PENDING")
            self.assertEqual((paid.delivery_fee, paid.total, paid.payment_status, paid.status),
                             (Decimal("5.00"), Decimal("25.00"), "paid", "processing"))
            self.assertEqual(paid.delivery_location, "Legacy address")
            self.assertEqual(paid.landmark, "Legacy landmark")
            self.assertEqual(paid.delivery_area_name, "Original name")
            self.assertEqual(paid.delivery_area, "")
            self.assertEqual(pending.delivery_area_name, "Historical fixture")
            self.assertIsNone(pending.delivery_fee)
            self.assertIsNone(pending.total)
            self.assertEqual(pending.status, "quote_pending")
            self.assertNotIn("orders_deliveryzone", connection.introspection.table_names())
            self.assertEqual(new_apps.get_model("orders", "Payment").objects.get(reference="migration-paid").status, "success")
        finally:
            MigrationExecutor(connection).migrate(current)
