import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch
import uuid

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import IntegrityError, OperationalError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from store.models import Category, Product

from .cart import CART_SESSION_KEY
from .delivery import DELIVERY_FEES
from .models import Order, OrderItem, OrderStatusHistory, Payment
from .payments import (
    PaystackError,
    amount_in_subunits,
    initialize_transaction,
    paystack_is_enabled,
    record_verified_transaction,
    validate_paystack_configuration,
)
from .services import confirm_delivery_quote, create_payment_attempt
from .views import GUEST_SESSION_KEY, PREVIEW_SESSION_KEY


@override_settings(
    STORAGES={
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    },
)
class CheckoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Accessories")
        cls.frame = Product.objects.create(category=cls.category, name="Frame", sku="FRAME", price="22.74", stock=4)
        cls.cable = Product.objects.create(category=cls.category, name="Cable", sku="CABLE", price="10.05", stock=10)

    def setUp(self):
        self.url = reverse("orders:checkout")

    def make_paystack_signature(self, payload):
        return hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            payload,
            hashlib.sha512,
        ).hexdigest()

    def prepare(self, quantity=2, product=None, client=None):
        browser = client or self.client
        product = product or self.frame
        browser.post(reverse("orders:cart_add", args=[product.pk]), {"quantity": quantity})
        response = browser.get(self.url)
        self.assertEqual(response.status_code, 200)
        return {
            "checkout_token": response.context["form"]["checkout_token"].value(),
            "customer_name": "Test Student", "customer_phone": "024 000 0000",
            "customer_email": "student@example.test", "delivery_location": "Test Hall, room 12",
            "delivery_area": "campus",
            "landmark": "Main entrance", "delivery_notes": "Call on arrival.",
        }

    def place(self, **changes):
        data = self.prepare()
        data.update(changes)
        response = self.client.post(self.url, data, follow=True)
        self.assertEqual(response.status_code, 200)
        return Order.objects.get(), response

    def place_legacy(self, **changes):
        order, _ = self.place(**changes)
        Order.objects.filter(pk=order.pk).update(
            delivery_area="", delivery_area_name="", delivery_fee=None, total=None, status=Order.Status.QUOTE_PENDING,
        )
        order.status_history.exclude(status=Order.Status.QUOTE_PENDING).delete()
        order.refresh_from_db()
        return order, self.client.get(order.get_absolute_url())

    def test_empty_cart_redirects_without_creating_an_order(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("orders:cart_detail"))
        self.assertFalse(Order.objects.exists())

    def test_preview_creates_no_order_and_displays_automatic_delivery_prices(self):
        self.prepare()
        response = self.client.get(self.url)
        self.assertContains(response, "Guest checkout")
        self.assertContains(response, "GH₵ 45.48")
        self.assertNotContains(response, "To be confirmed")
        self.assertContains(response, "Palms Eatery")
        self.assertContains(response, "Submit order request")
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertFalse(Order.objects.exists())

    def test_guest_checkout_creates_payable_unpaid_order_and_clears_cart(self):
        order, response = self.place()
        self.assertContains(response, order.number)
        self.assertContains(response, "Your order request is saved")
        self.assertContains(response, "Awaiting payment")
        self.assertContains(response, "Payment")
        self.assertContains(response, "Order status")
        self.assertContains(response, "No payment has been taken.")
        self.assertContains(response, "Final total")
        self.assertNotContains(response, "To be confirmed")
        self.assertContains(response, "Continue shopping")
        self.assertNotContains(response, "View my orders")
        self.assertContains(response, 'aria-label="Cart, 0 items"')
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(order.subtotal, Decimal("45.48"))
        self.assertEqual(order.delivery_fee, Decimal("0.00"))
        self.assertEqual(order.total, order.subtotal)
        self.assertEqual(order.customer_phone, "+233240000000")
        self.assertEqual(order.delivery_location, "Test Hall, room 12")
        self.assertEqual(order.landmark, "Main entrance")
        self.assertEqual(order.delivery_notes, "Call on arrival.")
        self.assertNotIn(CART_SESSION_KEY, self.client.session)
        self.assertNotIn(PREVIEW_SESSION_KEY, self.client.session)
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.stock, 4)

    def test_guest_order_history_and_detail_are_scoped_to_the_browser_session(self):
        order, _ = self.place_legacy()
        history_url = reverse("orders:order_list")
        detail_url = order.get_absolute_url()

        history = self.client.get(history_url)
        self.assertEqual(history.status_code, 200)
        self.assertContains(history, f"#{order.number}")
        self.assertContains(history, "Quote pending")
        self.assertContains(history, "Total to be confirmed")
        self.assertContains(history, "View order")
        self.assertContains(history, f'href="{detail_url}"')

        detail = self.client.get(detail_url)
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, order.number)
        self.assertContains(detail, "Placed")
        self.assertContains(detail, "Your items")
        self.assertContains(detail, "Order status progression")
        self.assertContains(detail, "This timeline shows order status, not a live courier location.")
        self.assertContains(detail, "Quote pending")
        self.assertNotContains(detail, "Awaiting payment")
        self.assertContains(detail, "Payment")
        self.assertContains(detail, "Final total")
        self.assertContains(detail, "To be confirmed")

        other_browser = Client()
        self.assertNotContains(other_browser.get(history_url), order.number)
        self.assertEqual(other_browser.get(detail_url).status_code, 404)

    def test_order_history_without_a_guest_session_shows_an_empty_state(self):
        response = self.client.get(reverse("orders:order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No orders yet")
        self.assertContains(response, "Browse the store")
        self.assertFalse(Order.objects.exists())

    def test_legacy_tracking_url_redirects_to_session_owned_orders(self):
        order, _ = self.place()
        tracking_url = reverse("orders:track")
        self.assertEqual(tracking_url, "/track/")
        response = self.client.get(tracking_url, follow=True)
        self.assertRedirects(response, reverse("orders:order_list"), status_code=301)
        self.assertContains(response, order.number)
        self.assertContains(response, order.status_label)
        self.assertContains(response, f'href="{order.get_absolute_url()}"')
        other = Client().get(tracking_url, follow=True)
        self.assertContains(other, "No orders yet")
        self.assertNotContains(other, order.number)
        self.assertEqual(self.client.head(tracking_url).status_code, 301)
        self.assertEqual(self.client.post(tracking_url).status_code, 405)

    def test_order_status_tones_follow_only_the_existing_status_choices(self):
        order, _ = self.place_legacy()
        expected = {
            Order.Status.QUOTE_PENDING: "pending",
            Order.Status.AWAITING_PAYMENT: "pending",
            Order.Status.PAID: "confirmed",
            Order.Status.PROCESSING: "processing",
            Order.Status.OUT_FOR_DELIVERY: "dispatched",
            Order.Status.DELIVERED: "delivered",
            "unrecognized": "neutral",
        }
        for status, tone in expected.items():
            with self.subTest(status=status):
                order.status = status
                self.assertEqual(order.status_tone, tone)
        order.status = Order.Status.QUOTE_PENDING
        self.assertEqual(order.status_label, "Quote pending")
        self.assertEqual(order.payment_status_label, "Unpaid")
        self.assertEqual(
            list(order.status_history.values_list("status", flat=True)),
            [Order.Status.QUOTE_PENDING],
        )

    def test_set_status_records_each_real_transition_once(self):
        order, _ = self.place_legacy()
        self.assertTrue(order.set_status(Order.Status.PROCESSING))
        self.assertFalse(order.set_status(Order.Status.PROCESSING))
        self.assertEqual(order.status, Order.Status.PROCESSING)
        self.assertEqual(
            list(order.status_history.values_list("status", flat=True)),
            [Order.Status.QUOTE_PENDING, Order.Status.PROCESSING],
        )
        with self.assertRaises(ValueError):
            order.set_status("not_a_real_status")

    def test_unsaved_order_cannot_record_a_status_change(self):
        with self.assertRaises(ValueError):
            Order().set_status(Order.Status.PROCESSING)

    def test_confirmation_shows_actual_status_history_and_legacy_fallback(self):
        order, _ = self.place_legacy()
        response = self.client.get(order.get_absolute_url())
        history = response.context["status_history"]
        self.assertEqual([event.status for event in history], [Order.Status.QUOTE_PENDING])
        self.assertContains(response, history[0].created_at.strftime("%d %b %Y, %H:%M"))

        OrderStatusHistory.objects.filter(order=order).delete()
        response = self.client.get(order.get_absolute_url())
        self.assertContains(response, "Status history is unavailable for this order.")
        self.assertContains(response, "Quote pending")

    def test_server_calculates_fee_totals_and_ignores_browser_money_and_status(self):
        order, response = self.place(delivery_area="ayeduase", subtotal="0.01", total="0.00", delivery_fee="0.00", price="0.01", payment_status="paid", status="delivered", stock="999")
        self.assertEqual(order.subtotal, Decimal("45.48"))
        self.assertEqual(order.delivery_fee, Decimal("10.00"))
        self.assertEqual(order.total, Decimal("55.48"))
        self.assertContains(response, "GH₵ 55.48")
        self.assertEqual(order.payment_status, "unpaid")
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)

    def test_free_delivery_is_distinct_from_an_unknown_quote(self):
        order, response = self.place(delivery_area="campus")
        self.assertEqual(order.delivery_fee, Decimal("0.00"))
        self.assertEqual(order.total, order.subtotal)
        self.assertNotContains(response, "To be confirmed")

    def test_snapshots_survive_product_changes_and_deletion(self):
        order, _ = self.place()
        item = order.items.get()
        self.assertEqual((item.product_name, item.sku, item.unit_price, item.quantity, item.line_total),
                         ("Frame", "FRAME", Decimal("22.74"), 2, Decimal("45.48")))
        Product.objects.filter(pk=self.frame.pk).update(name="Renamed", sku="NEW-SKU", price="99.00", is_available=False)
        response = self.client.get(order.get_absolute_url())
        self.assertContains(response, "GH₵ 22.74")
        self.assertNotContains(response, "NEW-SKU")
        self.frame.delete()
        item.refresh_from_db()
        self.assertIsNone(item.product_id)
        self.assertContains(self.client.get(order.get_absolute_url()), "GH₵ 45.48")

    def test_multiple_product_lines_and_decimal_arithmetic_are_saved_correctly(self):
        self.prepare(3, self.cable)
        data = self.prepare(2, self.frame)
        response = self.client.post(self.url, data, follow=True)
        order = Order.objects.get()
        self.assertEqual(order.items.count(), 2)
        self.assertEqual(order.items.get(product=self.cable).line_total, Decimal("30.15"))
        self.assertEqual(order.subtotal, Decimal("75.63"))
        self.assertContains(response, "GH₵ 75.63")

    def test_invalid_customer_details_keep_cart_and_create_no_order(self):
        data = self.prepare()
        for changes, field in (({"customer_name": " "}, "customer_name"), ({"customer_phone": "abc"}, "customer_phone"),
                               ({"customer_email": "bad-email"}, "customer_email"), ({"delivery_location": ""}, "delivery_location"),
                               ({"delivery_notes": "x" * 1001}, "delivery_notes")):
            with self.subTest(changes=changes):
                response = self.client.post(self.url, {**data, **changes})
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["form"].errors)
                self.assertContains(response, "Test Hall" if field != "delivery_location" else "Test Student")
                self.assertFalse(Order.objects.exists())
                self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.frame.pk)], 2)

    def test_optional_details_may_be_empty(self):
        order, _ = self.place(customer_email="", delivery_notes="")
        self.assertEqual(order.customer_email, "")
        self.assertEqual(order.delivery_notes, "")

    @override_settings(CHECKOUT_DELIVERY_FEE="12.50")
    def test_pickup_has_zero_fee_and_needs_no_delivery_address(self):
        order, response = self.place(delivery_area="pickup", delivery_location="", landmark="")
        self.assertEqual(order.delivery_method, Order.DeliveryMethod.PICKUP)
        self.assertEqual(order.delivery_fee, Decimal("0.00"))
        self.assertEqual(order.total, Decimal("45.48"))
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        self.assertContains(response, "Pickup")
        self.assertNotContains(response, "To be confirmed")
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.stock, 4)

    def test_delivery_method_and_campus_landmark_are_validated(self):
        data = self.prepare()
        for changes, field in (({"delivery_area": ""}, "delivery_area"),
                               ({"delivery_area": "free"}, "delivery_area"),
                               ({"landmark": " "}, "landmark"), ({"customer_phone": ""}, "customer_phone")):
            with self.subTest(changes=changes):
                response = self.client.post(self.url, {**data, **changes})
                self.assertIn(field, response.context["form"].errors)
                self.assertFalse(Order.objects.exists())

    def test_confirmation_escapes_customer_supplied_html(self):
        order, response = self.place(customer_name="<script>alert(1)</script>", delivery_notes="<img src=x onerror=alert(1)>")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")
        self.assertContains(response, "&lt;script&gt;")

    def test_changed_price_requires_review_and_an_explicit_second_submission(self):
        data = self.prepare()
        Product.objects.filter(pk=self.frame.pk).update(price="25.00")
        response = self.client.post(self.url, data)
        self.assertContains(response, "Your cart or prices have changed.")
        self.assertContains(response, "GH₵ 50.00")
        self.assertFalse(Order.objects.exists())
        data["checkout_token"] = response.context["form"]["checkout_token"].value()
        self.client.post(self.url, data)
        self.assertEqual(Order.objects.get().subtotal, Decimal("50.00"))

    def test_changed_delivery_fee_requires_review(self):
        data = self.prepare()
        data["delivery_area"] = "ayeduase"
        with patch.dict(DELIVERY_FEES, {"ayeduase": Decimal("12.00")}):
            response = self.client.post(self.url, data)
        self.assertContains(response, "Your cart or prices have changed.")
        self.assertFalse(Order.objects.exists())

    def test_reduced_stock_is_not_silently_submitted_with_a_smaller_quantity(self):
        data = self.prepare(4)
        Product.objects.filter(pk=self.frame.pk).update(stock=2)
        response = self.client.post(self.url, data)
        self.assertContains(response, "available stock for Frame has changed")
        self.assertFalse(Order.objects.exists())
        self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.frame.pk)], 2)
        data["checkout_token"] = response.context["form"]["checkout_token"].value()
        self.client.post(self.url, data)
        self.assertEqual(Order.objects.get().items.get().quantity, 2)

    def test_unknown_zero_or_hidden_products_fail_final_validation(self):
        for changes in ({"stock": None}, {"stock": 0}, {"is_available": False}):
            with self.subTest(changes=changes):
                Product.objects.filter(pk=self.frame.pk).update(stock=4, is_available=True)
                data = self.prepare()
                Product.objects.filter(pk=self.frame.pk).update(**changes)
                response = self.client.post(self.url, data, follow=True)
                self.assertContains(response, "Your cart is empty")
                self.assertFalse(Order.objects.exists())

    def test_deactivated_category_or_deleted_product_cannot_be_ordered(self):
        data = self.prepare()
        Category.objects.filter(pk=self.category.pk).update(is_active=False)
        self.client.post(self.url, data)
        self.assertFalse(Order.objects.exists())
        Category.objects.filter(pk=self.category.pk).update(is_active=True)
        data = self.prepare()
        self.frame.delete()
        self.client.post(self.url, data)
        self.assertFalse(Order.objects.exists())

    def test_cart_change_in_another_tab_requires_fresh_review(self):
        data = self.prepare()
        self.client.post(reverse("orders:cart_add", args=[self.cable.pk]), {"quantity": 1})
        response = self.client.post(self.url, data)
        self.assertContains(response, "Your cart or prices have changed.")
        self.assertFalse(Order.objects.exists())

    def test_stale_tab_cannot_use_a_newer_preview_to_accept_different_prices(self):
        data = self.prepare()
        Product.objects.filter(pk=self.frame.pk).update(price="25.00")
        self.client.get(self.url)
        response = self.client.post(self.url, data)
        self.assertContains(response, "This checkout has expired or changed.")
        self.assertFalse(Order.objects.exists())

    def test_repeated_submission_and_refresh_return_the_same_order(self):
        data = self.prepare()
        self.client.post(self.url, data)
        order = Order.objects.get()
        response = self.client.post(self.url, data)
        self.assertRedirects(response, order.get_absolute_url())
        self.client.get(order.get_absolute_url())
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(OrderItem.objects.count(), 1)

    def test_retry_of_old_order_does_not_clear_a_new_cart(self):
        data = self.prepare()
        self.client.post(self.url, data)
        self.client.post(reverse("orders:cart_add", args=[self.cable.pk]), {"quantity": 3})
        self.client.post(self.url, data)
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.cable.pk): 3})

    def test_missing_invalid_or_forged_checkout_tokens_cannot_create_orders(self):
        data = self.prepare()
        for token in ("", "invalid", str(uuid.uuid4())):
            with self.subTest(token=token):
                self.client.post(self.url, {**data, "checkout_token": token})
                self.assertFalse(Order.objects.exists())

    def test_direct_post_without_preview_is_rejected(self):
        data = self.prepare()
        session = self.client.session
        session.pop(PREVIEW_SESSION_KEY)
        session.save()
        self.client.post(self.url, data)
        self.assertFalse(Order.objects.exists())

    def test_other_browser_cannot_view_or_replay_an_order(self):
        data = self.prepare()
        self.client.post(self.url, data)
        order = Order.objects.get()
        other = Client()
        other_data = self.prepare(client=other)
        self.assertEqual(other.get(order.get_absolute_url()).status_code, 404)
        other.post(self.url, {**other_data, "checkout_token": data["checkout_token"]})
        self.assertEqual(Order.objects.count(), 1)
        self.assertEqual(Client().get(order.get_absolute_url()).status_code, 404)
        self.assertIn("no-store", self.client.get(order.get_absolute_url()).headers["Cache-Control"])

    def test_checkout_requires_csrf_and_mutation_is_post_only(self):
        browser = Client(enforce_csrf_checks=True)
        browser.get(self.frame.get_absolute_url())
        csrf = browser.cookies["csrftoken"].value
        browser.post(reverse("orders:cart_add", args=[self.frame.pk]), {"quantity": 1, "csrfmiddlewaretoken": csrf})
        response = browser.get(self.url)
        data = {"checkout_token": response.context["form"]["checkout_token"].value(),
                "customer_name": "CSRF Test", "customer_phone": "0240000000", "delivery_location": "Test Hall",
                "delivery_area": "campus", "landmark": "Entrance"}
        self.assertEqual(browser.post(self.url, data).status_code, 403)
        response = browser.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.put(self.url).status_code, 405)
        self.assertEqual(browser.post(Order.objects.get().get_absolute_url()).status_code, 403)

    def test_partial_order_creation_rolls_back_and_cart_can_be_retried(self):
        data = self.prepare()
        with patch("orders.services.OrderItem.objects.bulk_create", side_effect=RuntimeError("simulated failure")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, data)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(OrderItem.objects.exists())
        self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.frame.pk)], 2)
        self.client.post(self.url, data)
        self.assertEqual(Order.objects.count(), 1)

    def test_sqlite_lock_is_reported_as_retryable_without_partial_order(self):
        data = self.prepare()
        with patch("orders.services.Order.save", side_effect=OperationalError("database is locked")):
            response = self.client.post(self.url, data)
        self.assertContains(response, "Checkout is busy.")
        self.assertFalse(Order.objects.exists())
        self.client.post(self.url, data)
        self.assertEqual(Order.objects.count(), 1)

    def test_forged_location_does_not_silently_become_free(self):
        data = self.prepare()
        response = self.client.post(self.url, {**data, "delivery_area": "free-delivery", "delivery_fee": "0"})
        self.assertIn("delivery_area", response.context["form"].errors)
        self.assertFalse(Order.objects.exists())

    def test_order_constraints_protect_totals_and_unique_checkout_tokens(self):
        order, _ = self.place(delivery_area="ayeduase")
        for changes in ({"subtotal": -1}, {"delivery_fee": -1}, {"total": "0.00"},
                        {"total": None}, {"delivery_fee": None}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                Order.objects.filter(pk=order.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.create(guest_id=order.guest_id, checkout_token=order.checkout_token,
                                 customer_name="Duplicate", customer_phone="0240000000", delivery_location="Test Hall", subtotal=0)
        item = order.items.get()
        for changes in ({"quantity": 0}, {"quantity": -1}, {"unit_price": -1}, {"line_total": "1.00"}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                OrderItem.objects.filter(pk=item.pk).update(**changes)

    def test_admin_can_review_orders_and_snapshots_without_editing_them(self):
        order, _ = self.place_legacy()
        admin = get_user_model().objects.create_superuser(username="order-admin", password=None)
        self.client.force_login(admin)
        response = self.client.get(reverse("admin:orders_order_changelist"), {"q": order.number})
        self.assertContains(response, order.number)
        url = reverse("admin:orders_order_change", args=[order.pk])
        response = self.client.get(url)
        self.assertContains(response, "FRAME")
        self.assertContains(response, "Test Hall, room 12")
        self.assertContains(response, reverse("admin:orders_order_quote", args=[order.pk]))
        self.assertEqual(self.client.post(url, {"payment_status": "paid"}).status_code, 403)
        self.assertEqual(self.client.get(reverse("admin:orders_order_add")).status_code, 403)
        self.assertEqual(self.client.post(reverse("admin:orders_order_delete", args=[order.pk])).status_code, 403)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_admin_quote_calculates_total_preserves_snapshots_and_stays_unpaid(self):
        order, _ = self.place_legacy()
        item_before = list(order.items.values())
        browser = Client()
        browser.force_login(get_user_model().objects.create_superuser(username="quote-admin", password=None))
        url = reverse("admin:orders_order_quote", args=[order.pk])
        self.assertContains(browser.get(url), "GH₵ 45.48")
        order.refresh_from_db()
        self.assertIsNone(order.total)
        response = browser.post(url, {"delivery_fee": "12.50", "total": "0.01", "subtotal": "0.00", "payment_status": "paid", "status": "delivered"})
        self.assertRedirects(response, reverse("admin:orders_order_change", args=[order.pk]))
        order.refresh_from_db()
        self.assertEqual(order.subtotal, Decimal("45.48"))
        self.assertEqual(order.delivery_fee, Decimal("12.50"))
        self.assertEqual(order.total, Decimal("57.98"))
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(list(order.items.values()), item_before)
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.stock, 4)
        response = self.client.get(order.get_absolute_url())
        self.assertContains(response, "Awaiting payment")
        self.assertContains(response, "GH₵ 57.98")
        self.assertNotContains(response, "To be confirmed")
        browser.post(url, {"delivery_fee": "999.00"})
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("1044.48"))
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)

    def test_admin_quote_requires_permission_and_csrf(self):
        order, _ = self.place_legacy()
        url = reverse("admin:orders_order_quote", args=[order.pk])
        self.assertEqual(Client().post(url, {"delivery_fee": "0.00"}).status_code, 302)
        viewer = get_user_model().objects.create_user(username="order-viewer", is_staff=True)
        viewer.user_permissions.add(Permission.objects.get(codename="view_order", content_type__app_label="orders"))
        browser = Client()
        browser.force_login(viewer)
        self.assertEqual(browser.get(url).status_code, 403)
        self.assertEqual(browser.post(url, {"delivery_fee": "0.00"}).status_code, 403)
        self.assertNotContains(browser.get(reverse("admin:orders_order_change", args=[order.pk])), url)
        admin = get_user_model().objects.create_superuser(username="csrf-admin", password=None)
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(admin)
        self.assertEqual(browser.post(url, {"delivery_fee": "0.00"}).status_code, 403)
        self.assertEqual(browser.put(url).status_code, 403)
        order.refresh_from_db()
        self.assertIsNone(order.total)

    def test_invalid_admin_quote_cannot_change_order(self):
        order, _ = self.place_legacy()
        browser = Client()
        browser.force_login(get_user_model().objects.create_superuser(username="fee-admin", password=None))
        url = reverse("admin:orders_order_quote", args=[order.pk])
        for fee in ("", "To be confirmed", "-1", "NaN", "Infinity", "1.234", "100000000"):
            with self.subTest(fee=fee):
                response = browser.post(url, {"delivery_fee": fee})
                self.assertEqual(response.status_code, 200)
                self.assertIn("delivery_fee", response.context["form"].errors)
                order.refresh_from_db()
                self.assertIsNone(order.total)
                self.assertEqual(order.status, Order.Status.QUOTE_PENDING)

    def test_pickup_quote_cannot_charge_delivery_and_reconfirmation_is_idempotent(self):
        order, _ = self.place(delivery_area="pickup")
        with self.assertRaises(ValidationError):
            confirm_delivery_quote(order_id=order.pk, fee=Decimal("5.00"))
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        confirm_delivery_quote(order_id=order.pk, fee=Decimal("0.00"))
        order.refresh_from_db()
        self.assertEqual(order.total, order.subtotal)
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)
        self.assertEqual(
            list(order.status_history.values_list("status", flat=True)),
            [Order.Status.QUOTE_PENDING, Order.Status.AWAITING_PAYMENT],
        )
        confirm_delivery_quote(order_id=order.pk, fee=Decimal("0.00"))
        self.assertEqual(order.status_history.count(), 2)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Order.objects.filter(pk=order.pk).update(delivery_fee=1, total=order.subtotal + 1)

    def test_model_save_always_derives_total(self):
        order, _ = self.place()
        order.delivery_fee = Decimal("3.05")
        order.total = Decimal("1.00")
        order.save(update_fields=["delivery_fee"])
        order.refresh_from_db()
        self.assertEqual(order.total, Decimal("48.53"))
        order.delivery_fee = None
        order.save(update_fields=["delivery_fee"])
        order.refresh_from_db()
        self.assertIsNone(order.total)

    def make_payable_order(self, **changes):
        order, _ = self.place(**changes)
        confirm_delivery_quote(order_id=order.pk, fee=Decimal("0.00"))
        order.refresh_from_db()
        return order

    def test_paystack_live_mode_defaults_disabled(self):
        self.assertFalse(settings.PAYSTACK_LIVE_MODE)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_test_credentials_are_valid_with_live_mode_disabled(self):
        validate_paystack_configuration()
        self.assertTrue(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_live_public_example",
        PAYSTACK_SECRET_KEY="sk_live_secret_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_live_credentials_are_rejected_when_live_mode_is_disabled(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_paystack_configuration()
        self.assertFalse(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_live_public_example",
        PAYSTACK_SECRET_KEY="sk_live_secret_example",
        PAYSTACK_LIVE_MODE=True,
    )
    def test_paystack_live_credentials_require_and_accept_explicit_live_mode(self):
        validate_paystack_configuration()
        self.assertTrue(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=True,
    )
    def test_paystack_live_mode_rejects_test_credentials_instead_of_falling_back(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_paystack_configuration()
        self.assertFalse(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="",
        PAYSTACK_SECRET_KEY="",
        PAYSTACK_LIVE_MODE=True,
    )
    def test_paystack_live_mode_rejects_missing_credentials(self):
        with self.assertRaises(PaystackError):
            validate_paystack_configuration()
        self.assertFalse(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_public_example",
        PAYSTACK_SECRET_KEY="sk_live_secret_example",
        PAYSTACK_LIVE_MODE=True,
    )
    def test_paystack_live_mode_rejects_mismatched_credentials(self):
        with self.assertRaises(ImproperlyConfigured):
            validate_paystack_configuration()
        self.assertFalse(paystack_is_enabled())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_live_public_secret-sentinel",
        PAYSTACK_SECRET_KEY="sk_live_secret-sentinel",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_secret_is_not_rendered_or_logged(self):
        order, _ = self.place()

        with self.assertLogs("orders.payments", level="ERROR") as captured:
            response = self.client.get(order.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("sk_live_secret-sentinel", response.content.decode())
        self.assertNotIn("sk_live_secret-sentinel", "\n".join(captured.output))

    def test_paystack_webhook_url_resolves_and_is_csrf_exempt(self):
        endpoint = reverse("orders:paystack_webhook")
        self.assertEqual(endpoint, "/orders/payments/paystack/webhook/")

        resolved = resolve(endpoint)
        self.assertEqual(resolved.view_name, "orders:paystack_webhook")
        self.assertTrue(getattr(resolved.func, "csrf_exempt", False))

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_order_page_exposes_payment_only_after_quote_confirmation(self):
        order = self.make_payable_order()
        response = self.client.get(order.get_absolute_url())
        self.assertContains(response, "Paystack test mode is enabled.")
        self.assertContains(response, reverse("orders:paystack_initialize"))
        self.assertContains(response, "Pay now · GH₵ 45.48")

        with override_settings(PAYSTACK_PUBLIC_KEY="", PAYSTACK_SECRET_KEY=""):
            unavailable = self.client.get(order.get_absolute_url())
        self.assertContains(unavailable, "Online payment is not configured right now.")

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_payment_initialization_uses_server_total_and_redirects_to_paystack(self, post):
        order = self.make_payable_order()
        post_response = Mock()

        def initialized_response():
            payment = Payment.objects.filter(order=order).latest("created_at")
            return {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/access-token",
                    "reference": payment.reference,
                    "access_code": "access-token",
                },
            }

        post_response.json.side_effect = initialized_response
        post.return_value = post_response

        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number, "amount": "0.01"},
        )
        payment = Payment.objects.get(order=order)
        self.assertRedirects(response, "https://checkout.paystack.com/access-token", fetch_redirect_response=False)
        post.assert_called_once()
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["amount"], 4548)
        self.assertEqual(payload["currency"], "GHS")
        self.assertEqual(payload["reference"], payment.reference)
        self.assertEqual(payment.amount, Decimal("45.48"))
        self.assertEqual(payment.status, Payment.Status.PENDING)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_payment_initialization_uses_order_snapshot_after_product_price_change(self, post):
        Product.objects.filter(pk=self.frame.pk).update(price="75.00")
        order = self.make_payable_order()
        self.assertEqual(order.subtotal, Decimal("150.00"))
        self.assertEqual(order.total, Decimal("150.00"))

        Product.objects.filter(pk=self.frame.pk).update(price="87.50")
        post_response = Mock()
        post_response.json.side_effect = lambda: {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/access-token",
                "reference": Payment.objects.filter(order=order).latest("created_at").reference,
            },
        }
        post.return_value = post_response

        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number, "amount": "175.00"},
        )

        self.assertEqual(response.status_code, 302)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 15000)
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal("150.00"))
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.price, Decimal("87.50"))

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_payment_initialization_uses_updated_confirmed_total(self, post):
        Product.objects.filter(pk=self.frame.pk).update(price="75.00")
        order, _ = self.place_legacy()
        order = confirm_delivery_quote(order_id=order.pk, fee=Decimal("20.00"))
        self.assertEqual(order.subtotal, Decimal("150.00"))
        self.assertEqual(order.total, Decimal("170.00"))

        confirm_delivery_quote(order_id=order.pk, fee=Decimal("35.00"))

        post_response = Mock()
        post_response.json.side_effect = lambda: {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/access-token",
                "reference": Payment.objects.filter(order=order).latest("created_at").reference,
            },
        }
        post.return_value = post_response

        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number, "amount": "185.00"},
        )

        self.assertEqual(response.status_code, 302)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 18500)
        self.assertEqual(Payment.objects.get(order=order).amount, Decimal("185.00"))
        order.refresh_from_db()
        self.assertEqual(order.delivery_fee, Decimal("35.00"))
        self.assertEqual(order.total, Decimal("185.00"))

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_payment_initialization_requires_current_stock_and_guest_ownership(self):
        order = self.make_payable_order()
        Product.objects.filter(pk=self.frame.pk).update(stock=0)
        response = self.client.post(reverse("orders:paystack_initialize"), {"order_number": order.number})
        self.assertRedirects(response, order.get_absolute_url())
        self.assertFalse(Payment.objects.filter(order=order).exists())

        other_browser = Client()
        response = other_browser.post(reverse("orders:paystack_initialize"), {"order_number": order.number})
        self.assertEqual(response.status_code, 404)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_pending_payment_shows_continue_payment_action(self):
        order = self.make_payable_order()
        create_payment_attempt(order_id=order.pk, email=order.customer_email)

        response = self.client.get(order.get_absolute_url())

        self.assertContains(response, "Order status")
        self.assertContains(response, "Awaiting payment")
        self.assertContains(response, "Payment")
        self.assertContains(response, "Payment pending")
        self.assertContains(response, "Continue payment")
        self.assertContains(response, "Your order has been created, but payment has not been completed.")
        self.assertNotContains(response, "Payment not completed")
        self.assertNotContains(response, "Try payment again")

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_abandoned_payment_can_be_retried_with_new_reference(self, post):
        order = self.make_payable_order()
        payment_1, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        payment_1_reference = payment_1.reference
        self.assertTrue(record_verified_transaction(payment_1.pk, {
            "reference": payment_1.reference,
            "status": "abandoned",
            "amount": 4548,
            "currency": "GHS",
            "id": 123,
        }))

        confirmation = self.client.get(order.get_absolute_url())
        self.assertContains(confirmation, "Payment not completed")
        self.assertContains(confirmation, "Try payment again")
        self.assertNotContains(confirmation, "Payment failed")

        post_response = Mock()
        post_response.json.side_effect = lambda: {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/retry-token",
                "reference": order.payments.first().reference,
            },
        }
        post.return_value = post_response
        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number},
        )

        self.assertRedirects(response, "https://checkout.paystack.com/retry-token", fetch_redirect_response=False)
        post.assert_called_once()
        payment_1.refresh_from_db()
        payment_2 = order.payments.first()
        self.assertNotEqual(payment_1_reference, payment_2.reference)
        self.assertEqual(post.call_args.kwargs["json"]["reference"], payment_2.reference)
        self.assertEqual(Payment.objects.filter(order=order).count(), 2)
        self.assertEqual(payment_1.reference, payment_1_reference)
        self.assertEqual(payment_1.status, Payment.Status.ABANDONED)
        self.assertEqual(payment_2.status, Payment.Status.PENDING)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paid_payment_shows_no_retry_action(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        order.set_status(Order.Status.PROCESSING)
        self.assertTrue(record_verified_transaction(payment.pk, {
            "reference": payment.reference,
            "status": "success",
            "amount": 4548,
            "currency": "GHS",
            "id": 123,
        }))

        response = self.client.get(order.get_absolute_url())

        self.assertContains(response, "Paid")
        self.assertContains(response, "Payment received")
        self.assertContains(response, "Order status")
        self.assertContains(response, "Processing")
        self.assertContains(response, f"Paystack reference: {payment.reference}")
        self.assertNotContains(response, "Try payment again")
        self.assertNotContains(response, "Continue payment")
        self.assertNotContains(
            response,
            f'action="{reverse("orders:paystack_initialize")}"',
        )
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PROCESSING)

    def test_successful_payment_reference_is_shown_instead_of_failed_attempt_reference(self):
        order = self.make_payable_order()
        payment_1, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        self.assertTrue(record_verified_transaction(payment_1.pk, {
            "reference": payment_1.reference,
            "status": "failed",
            "amount": 4548,
            "currency": "GHS",
            "id": 123,
        }))
        payment_2, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        self.assertTrue(record_verified_transaction(payment_2.pk, {
            "reference": payment_2.reference,
            "status": "success",
            "amount": 4548,
            "currency": "GHS",
            "id": 456,
        }))

        response = self.client.get(order.get_absolute_url())

        self.assertContains(response, f"Paystack reference: {payment_2.reference}")
        self.assertNotContains(response, f"Paystack reference: {payment_1.reference}")
        self.assertEqual(Payment.objects.filter(order=order).count(), 2)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_payment_initialization_is_refused_when_final_unit_sells_after_order(self, post):
        Product.objects.filter(pk=self.frame.pk).update(stock=1)
        checkout_data = self.prepare(quantity=1)
        checkout_response = self.client.post(self.url, checkout_data)
        self.assertEqual(checkout_response.status_code, 302)
        order = Order.objects.get()
        order = confirm_delivery_quote(order_id=order.pk, fee=Decimal("0.00"))

        # A different order consumes the only unit after this order was placed.
        Product.objects.filter(pk=self.frame.pk).update(stock=0)

        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number},
        )

        self.assertRedirects(response, order.get_absolute_url())
        post.assert_not_called()
        self.assertFalse(Payment.objects.filter(order=order).exists())

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_payment_form_collects_email_when_checkout_email_was_omitted(self, post):
        order = self.make_payable_order(customer_email="")
        post_response = Mock()
        post_response.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/access-token",
                "reference": None,
            },
        }
        post.return_value = post_response
        payment, _ = create_payment_attempt(order_id=order.pk, email="payer@example.test")
        post_response.json.return_value["data"]["reference"] = payment.reference

        response = self.client.post(
            reverse("orders:paystack_initialize"),
            {"order_number": order.number, "email": "payer@example.test"},
        )
        self.assertEqual(response.status_code, 302)
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.customer_email, "payer@example.test")
        self.assertEqual(order.customer_email, "payer@example.test")

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.get")
    def test_verified_callback_marks_payment_paid_without_advancing_order_status(self, get):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        get_response = Mock()
        get_response.json.return_value = {
            "status": True,
            "data": {
                "reference": payment.reference,
                "status": "success",
                "amount": 4548,
                "currency": "GHS",
                "id": 12345,
            },
        }
        get.return_value = get_response

        callback = reverse("orders:paystack_callback")
        response = self.client.get(callback, {"reference": payment.reference, "trxref": payment.reference})
        self.assertRedirects(response, order.get_absolute_url())
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(order.status, Order.Status.AWAITING_PAYMENT)

        self.client.get(callback, {"reference": payment.reference})
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        order.refresh_from_db()
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.get")
    def test_callback_rejects_wrong_amount_or_currency(self, get):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        callback = reverse("orders:paystack_callback")
        for changes in ({"amount": 4547}, {"currency": "USD"}):
            with self.subTest(changes=changes):
                get_response = Mock()
                get_response.json.return_value = {
                    "status": True,
                    "data": {
                        "reference": payment.reference,
                        "status": "success",
                        "amount": 4548,
                        "currency": "GHS",
                        **changes,
                    },
                }
                get.return_value = get_response
                self.client.get(callback, {"reference": payment.reference})
                payment.refresh_from_db()
                order.refresh_from_db()
                self.assertEqual(payment.status, Payment.Status.PENDING)
                self.assertEqual(order.payment_status, Order.PaymentStatus.UNPAID)

    def test_failed_payment_retry_creates_a_new_auditable_reference(self):
        order = self.make_payable_order()
        first, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        self.assertTrue(record_verified_transaction(first.pk, {
            "reference": first.reference,
            "status": "failed",
            "amount": 4548,
            "currency": "GHS",
            "id": 123,
        }))
        first.refresh_from_db()
        second, should_initialize = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        self.assertTrue(should_initialize)
        self.assertNotEqual(first.reference, second.reference)
        self.assertEqual(Payment.objects.filter(order=order).count(), 2)
        self.assertEqual(first.status, Payment.Status.FAILED)

    def test_successful_retry_preserves_failed_payment_attempt(self):
        order = self.make_payable_order()
        payment_1, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)
        payment_1_reference = payment_1.reference
        self.assertTrue(record_verified_transaction(payment_1.pk, {
            "reference": payment_1.reference,
            "status": "failed",
            "amount": 4548,
            "currency": "GHS",
            "id": 123,
        }))

        payment_2, should_initialize = create_payment_attempt(
            order_id=order.pk,
            email=order.customer_email,
        )
        self.assertTrue(should_initialize)
        self.assertNotEqual(payment_1.reference, payment_2.reference)
        self.assertTrue(record_verified_transaction(payment_2.pk, {
            "reference": payment_2.reference,
            "status": "success",
            "amount": 4548,
            "currency": "GHS",
            "id": 456,
        }))

        payment_1.refresh_from_db()
        payment_2.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(Payment.objects.filter(order=order).count(), 2)
        self.assertEqual(payment_1.order_id, order.pk)
        self.assertEqual(payment_2.order_id, order.pk)
        self.assertEqual(payment_1.reference, payment_1_reference)
        self.assertEqual(payment_1.status, Payment.Status.FAILED)
        self.assertEqual(payment_2.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_marks_payment_paid(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": int(payment.amount * 100),
                "currency": payment.currency,
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = self.make_paystack_signature(raw_payload)

        response = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_rejects_invalid_signature(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": int(payment.amount * 100),
                "currency": payment.currency,
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")

        missing_signature = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
        )
        self.assertEqual(missing_signature.status_code, 401)

        response = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid-signature",
        )

        self.assertEqual(response.status_code, 401)
        payment.refresh_from_db()
        self.assertNotEqual(payment.status, Payment.Status.SUCCESS)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_rejects_amount_mismatch(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": int(payment.amount * 100) + 100,
                "currency": payment.currency,
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = self.make_paystack_signature(raw_payload)

        response = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 400)
        payment.refresh_from_db()
        self.assertNotEqual(payment.status, Payment.Status.SUCCESS)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_rejects_currency_mismatch(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": int(payment.amount * 100),
                "currency": "USD",
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = self.make_paystack_signature(raw_payload)

        response = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 400)
        payment.refresh_from_db()
        self.assertNotEqual(payment.status, Payment.Status.SUCCESS)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_rejects_unknown_reference(self):
        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": "unknown-payment-reference",
                "amount": 10000,
                "currency": "GHS",
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = self.make_paystack_signature(raw_payload)

        response = self.client.post(
            reverse("orders:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 404)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    def test_paystack_webhook_is_idempotent(self):
        order = self.make_payable_order()
        payment, _ = create_payment_attempt(order_id=order.pk, email=order.customer_email)

        payload = {
            "event": "charge.success",
            "data": {
                "status": "success",
                "reference": payment.reference,
                "amount": int(payment.amount * 100),
                "currency": payment.currency,
            },
        }
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = self.make_paystack_signature(raw_payload)
        endpoint = reverse("orders:paystack_webhook")

        responses = [
            self.client.post(
                endpoint,
                data=raw_payload,
                content_type="application/json",
                HTTP_X_PAYSTACK_SIGNATURE=signature,
            )
            for _ in range(3)
        ]

        self.assertEqual([response.status_code for response in responses], [200, 200, 200])
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(Payment.objects.filter(order=order).count(), 1)
        self.assertEqual(
            Payment.objects.filter(order=order, status=Payment.Status.SUCCESS).count(),
            1,
        )
        self.assertEqual(Order.objects.filter(pk=order.pk).count(), 1)
        self.assertEqual(payment.reference, payload["data"]["reference"])
        self.assertEqual(payment.status, Payment.Status.SUCCESS)
        self.assertEqual(order.payment_status, Order.PaymentStatus.PAID)
        self.assertEqual(
            order.status_history.filter(status=Order.Status.AWAITING_PAYMENT).count(),
            1,
        )

    def test_paystack_amount_uses_pesewas_and_rejects_invalid_values(self):
        self.assertEqual(amount_in_subunits(Decimal("125.50")), 12550)
        for amount in (Decimal("0"), Decimal("-1.00"), Decimal("1.001"), Decimal("NaN")):
            with self.subTest(amount=amount), self.assertRaises(PaystackError):
                amount_in_subunits(amount)

    @override_settings(
        PAYSTACK_PUBLIC_KEY="pk_test_example",
        PAYSTACK_SECRET_KEY="sk_test_example",
        PAYSTACK_LIVE_MODE=False,
    )
    @patch("orders.payments.requests.post")
    def test_paystack_initialization_rejects_non_paystack_redirects(self, post):
        response = Mock()
        response.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://attacker.example/collect",
                "reference": "expected-reference",
            },
        }
        post.return_value = response
        with self.assertRaises(PaystackError):
            initialize_transaction(
                email="student@example.test",
                amount=Decimal("20.00"),
                reference="expected-reference",
                callback_url="https://campusfriend.example/payments/paystack/callback/",
            )
