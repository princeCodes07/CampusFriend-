import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import resolve, reverse

from orders.payments import PaystackError

from .models import (
    PhoneModel,
    PhoneRepairPrice,
    PhoneRepairService,
    RepairNotification,
    RepairPayment,
    RepairRequest,
    RepairStatusHistory,
)
from .payments import (
    RepairPaymentError,
    create_payment_attempt,
    record_verified_transaction,
)


PAYSTACK_SETTINGS = {
    "PAYSTACK_PUBLIC_KEY": "pk_test_repairs_example",
    "PAYSTACK_SECRET_KEY": "sk_test_repairs_example",
    "PAYSTACK_LIVE_MODE": False,
}


@override_settings(**PAYSTACK_SETTINGS)
class RepairPaymentTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = PhoneRepairService.objects.get(slug="fix-broken-screen")
        cls.phone_model = PhoneModel.objects.create(
            brand="Apple",
            model_name="iPhone 15",
            phone_type=PhoneModel.PhoneType.IPHONE,
        )
        cls.price = PhoneRepairPrice.objects.create(
            service=cls.service,
            phone_model=cls.phone_model,
            price=Decimal("420.00"),
        )

    def setUp(self):
        self.owner_session = "owner-session-123"
        session = self.client.session
        session["repair_guest_session_id"] = self.owner_session
        session.save()

    def make_repair(self, **changes):
        values = {
            "request_type": RepairRequest.RequestType.FIXED_PRICE_PHONE,
            "customer_name": "Ama Mensah",
            "phone_number": "0240000000",
            "email": "ama@example.test",
            "guest_session_id": self.owner_session,
            "phone_type": self.phone_model.phone_type,
            "phone_model": self.phone_model,
            "service": self.service,
            "confirmed_price": self.price.price,
            "status": RepairRequest.Status.PRICE_CONFIRMED,
        }
        values.update(changes)
        return RepairRequest.objects.create(**values)

    @staticmethod
    def signed_payload(payload):
        raw_payload = json.dumps(payload).encode("utf-8")
        signature = hmac.new(
            settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
            raw_payload,
            hashlib.sha512,
        ).hexdigest()
        return raw_payload, signature

    def successful_webhook_payload(self, payment, **changes):
        data = {
            "status": "success",
            "reference": payment.reference,
            "amount": 42000,
            "currency": "GHS",
            "id": 12345,
        }
        data.update(changes)
        return {"event": "charge.success", "data": data}

    def test_confirmation_persists_fixed_price_repair_from_server_catalogue(self):
        response = self.client.post(
            reverse("repairs:phone_service", args=[self.service.slug]),
            {
                "phone_type": PhoneModel.PhoneType.IPHONE,
                "phone_model": self.phone_model.pk,
                "confirm_price": "1",
                "name": "Ama Mensah",
                "phone_number": "0240000000",
                "email": "ama@example.test",
                "price": "0.01",
                "amount": "0.01",
            },
        )

        repair = RepairRequest.objects.get(customer_name="Ama Mensah")
        self.assertRedirects(response, reverse("repairs:repair_detail", args=[repair.reference]))
        self.assertEqual(repair.request_type, RepairRequest.RequestType.FIXED_PRICE_PHONE)
        self.assertEqual(repair.confirmed_price, Decimal("420.00"))
        self.assertEqual(repair.status, RepairRequest.Status.PRICE_CONFIRMED)
        self.assertEqual(repair.status_history.count(), 1)

    def test_payment_model_stores_positive_server_amount_and_unique_attempt_references(self):
        repair = self.make_repair()
        first, should_initialize = create_payment_attempt(repair.pk, repair.email)
        self.assertTrue(should_initialize)
        self.assertEqual(first.amount, Decimal("420.00"))
        self.assertEqual(first.currency, "GHS")
        self.assertEqual(first.status, RepairPayment.Status.PENDING)

        self.assertTrue(record_verified_transaction(first.pk, {
            "reference": first.reference,
            "status": "failed",
            "amount": 42000,
            "currency": "GHS",
            "id": 123,
        }))
        second, should_initialize = create_payment_attempt(repair.pk, repair.email)
        self.assertTrue(should_initialize)
        self.assertNotEqual(first.reference, second.reference)
        self.assertEqual(RepairPayment.objects.filter(repair_request=repair).count(), 2)
        first.refresh_from_db()
        self.assertEqual(first.status, RepairPayment.Status.FAILED)

    @patch("orders.payments.requests.post")
    def test_initialization_uses_authoritative_amount_and_currency(self, post):
        repair = self.make_repair()
        post.return_value = Mock()
        post.return_value.json.return_value = {
            "status": True,
            "data": {
                "authorization_url": "https://checkout.paystack.com/repair-test",
                "reference": RepairPayment.objects.first().reference if RepairPayment.objects.exists() else None,
            },
        }

        def response_payload():
            payment = RepairPayment.objects.get(repair_request=repair)
            return {
                "status": True,
                "data": {
                    "authorization_url": "https://checkout.paystack.com/repair-test",
                    "reference": payment.reference,
                },
            }

        post.return_value.json.side_effect = response_payload
        response = self.client.post(
            reverse("repairs:paystack_initialize", args=[repair.reference]),
            {"price": "0.01", "amount": "0.01", "currency": "USD"},
        )

        payment = RepairPayment.objects.get(repair_request=repair)
        self.assertRedirects(response, "https://checkout.paystack.com/repair-test", fetch_redirect_response=False)
        self.assertEqual(post.call_args.kwargs["json"]["amount"], 42000)
        self.assertEqual(post.call_args.kwargs["json"]["currency"], "GHS")
        self.assertEqual(post.call_args.kwargs["json"]["reference"], payment.reference)
        self.assertEqual(payment.amount, Decimal("420.00"))
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)

    @patch("orders.payments.requests.post")
    def test_inactive_service_model_and_missing_price_never_initialize_paystack(self, post):
        repair = self.make_repair()
        invalidations = (
            (PhoneRepairService.objects.filter(pk=self.service.pk), {"active": False}),
            (PhoneModel.objects.filter(pk=self.phone_model.pk), {"active": False}),
            (PhoneRepairPrice.objects.filter(pk=self.price.pk), {"active": False}),
        )
        for queryset, changes in invalidations:
            with self.subTest(changes=changes):
                queryset.update(**changes)
                response = self.client.post(reverse("repairs:paystack_initialize", args=[repair.reference]))
                self.assertEqual(response.status_code, 302)
                post.assert_not_called()
                self.assertFalse(RepairPayment.objects.filter(repair_request=repair).exists())
                queryset.update(**{key: (not value) if isinstance(value, bool) else value for key, value in changes.items()})

    @patch("orders.payments.requests.post")
    def test_changed_catalogue_price_requires_reconfirmation_before_initialization(self, post):
        repair = self.make_repair()
        PhoneRepairPrice.objects.filter(pk=self.price.pk).update(price=Decimal("450.00"))

        response = self.client.post(reverse("repairs:paystack_initialize", args=[repair.reference]))

        self.assertEqual(response.status_code, 302)
        self.assertIn(f"repair_reference={repair.reference}", response["Location"])
        post.assert_not_called()
        self.assertFalse(RepairPayment.objects.filter(repair_request=repair).exists())

    def test_price_reconfirmation_updates_same_repair_and_keeps_failed_attempt(self):
        repair = self.make_repair()
        RepairStatusHistory.objects.create(
            repair_request=repair,
            status=RepairRequest.Status.PRICE_CONFIRMED,
            note="Student confirmed the current repair price.",
        )
        attempt, _ = create_payment_attempt(repair.pk, repair.email)
        record_verified_transaction(attempt.pk, {
            "reference": attempt.reference,
            "status": "failed",
            "amount": 42000,
            "currency": "GHS",
        })
        PhoneRepairPrice.objects.filter(pk=self.price.pk).update(price=Decimal("450.00"))

        response = self.client.post(
            reverse("repairs:phone_service", args=[self.service.slug]),
            {
                "phone_type": self.phone_model.phone_type,
                "phone_model": self.phone_model.pk,
                "confirm_price": "1",
                "repair_reference": repair.reference,
                "name": repair.customer_name,
                "phone_number": repair.phone_number,
                "email": repair.email,
            },
        )

        self.assertRedirects(response, reverse("repairs:repair_detail", args=[repair.reference]))
        repair.refresh_from_db()
        attempt.refresh_from_db()
        self.assertEqual(repair.confirmed_price, Decimal("450.00"))
        self.assertEqual(RepairRequest.objects.count(), 1)
        self.assertEqual(attempt.status, RepairPayment.Status.FAILED)
        self.assertEqual(repair.status_history.filter(status=RepairRequest.Status.PRICE_CONFIRMED).count(), 2)

    def test_request_based_repairs_cannot_create_payment(self):
        repair = self.make_repair(
            request_type=RepairRequest.RequestType.LAPTOP,
            service=None,
            phone_model=None,
            phone_type="",
            confirmed_price=None,
            status=RepairRequest.Status.REQUESTED,
        )

        response = self.client.post(reverse("repairs:paystack_initialize", args=[repair.reference]), follow=True)

        self.assertContains(response, "Payment is not required for this repair request yet.")
        self.assertFalse(RepairPayment.objects.filter(repair_request=repair).exists())

    def test_unapproved_priceable_service_is_not_payable(self):
        service = PhoneRepairService.objects.create(
            name="Unapproved repair",
            slug="unapproved-repair",
            priceable=True,
        )
        PhoneRepairPrice.objects.create(service=service, phone_model=self.phone_model, price="100.00")
        repair = self.make_repair(service=service)

        with self.assertRaises(RepairPaymentError):
            create_payment_attempt(repair.pk, repair.email)

    @patch("repairs.views.verify_transaction")
    def test_verified_callback_marks_only_payment_paid_and_not_repair_completed(self, verify):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        verify.return_value = {
            "reference": payment.reference,
            "status": "success",
            "amount": 42000,
            "currency": "GHS",
            "id": 12345,
        }

        response = self.client.get(reverse("repairs:paystack_callback"), {
            "reference": payment.reference,
            "trxref": payment.reference,
        })

        self.assertRedirects(response, reverse("repairs:repair_detail", args=[repair.reference]))
        payment.refresh_from_db()
        repair.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PAID)
        self.assertIsNotNone(payment.paid_at)
        self.assertEqual(payment.provider_transaction_id, "12345")
        self.assertEqual(repair.status, RepairRequest.Status.PAID)
        self.assertNotEqual(repair.status, RepairRequest.Status.COMPLETED)
        self.assertEqual(repair.status_history.filter(status=RepairRequest.Status.PAID).count(), 1)

    @patch("repairs.views.verify_transaction")
    def test_callback_rejects_mismatched_reference_amount_or_currency(self, verify):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        wrong_values = (
            {"reference": "different-reference"},
            {"amount": 41999},
            {"currency": "USD"},
        )
        for changes in wrong_values:
            with self.subTest(changes=changes):
                verify.return_value = {
                    "reference": payment.reference,
                    "status": "success",
                    "amount": 42000,
                    "currency": "GHS",
                    **changes,
                }
                self.client.get(reverse("repairs:paystack_callback"), {"reference": payment.reference})
                payment.refresh_from_db()
                repair.refresh_from_db()
                self.assertEqual(payment.status, RepairPayment.Status.PENDING)
                self.assertEqual(repair.status, RepairRequest.Status.PAYMENT_PENDING)

    @patch("repairs.views.verify_transaction", side_effect=PaystackError("verification unavailable"))
    def test_fake_browser_success_does_not_mark_payment_paid(self, verify):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)

        self.client.get(reverse("repairs:paystack_callback"), {
            "reference": payment.reference,
            "status": "success",
        })

        payment.refresh_from_db()
        repair.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)
        self.assertEqual(repair.status, RepairRequest.Status.PAYMENT_PENDING)
        verify.assert_called_once_with(payment.reference)

    @patch("repairs.views.verify_transaction")
    def test_failed_verified_callback_makes_retry_available_and_preserves_attempt(self, verify):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        verify.return_value = {
            "reference": payment.reference,
            "status": "failed",
            "amount": 42000,
            "currency": "GHS",
        }

        self.client.get(reverse("repairs:paystack_callback"), {"reference": payment.reference})

        payment.refresh_from_db()
        detail = self.client.get(reverse("repairs:repair_detail", args=[repair.reference]))
        self.assertEqual(payment.status, RepairPayment.Status.FAILED)
        self.assertContains(detail, "Payment failed. Retry is available.")
        second, should_initialize = create_payment_attempt(repair.pk, repair.email)
        self.assertTrue(should_initialize)
        self.assertNotEqual(payment.reference, second.reference)
        self.assertEqual(RepairPayment.objects.filter(repair_request=repair).count(), 2)

    def test_callback_and_initialization_require_session_ownership(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        other_client = Client()

        self.assertEqual(
            other_client.post(reverse("repairs:paystack_initialize", args=[repair.reference])).status_code,
            404,
        )
        self.assertEqual(
            other_client.get(reverse("repairs:paystack_callback"), {"reference": payment.reference}).status_code,
            404,
        )
        own_response = self.client.get(reverse("repairs:repair_detail", args=[repair.reference]))
        self.assertEqual(own_response.status_code, 200)
        self.assertEqual(other_client.get(reverse("repairs:repair_detail", args=[repair.reference])).status_code, 404)

    def test_another_repair_reference_cannot_be_used_to_confirm_payment(self):
        repair_a = self.make_repair()
        repair_b = self.make_repair(guest_session_id="different-owner")
        payment_b, _ = create_payment_attempt(repair_b.pk, repair_b.email)
        self.assertEqual(
            self.client.get(reverse("repairs:paystack_callback"), {"reference": payment_b.reference}).status_code,
            404,
        )
        self.assertNotEqual(repair_a.guest_session_id, repair_b.guest_session_id)

    def test_callback_rejects_mismatched_query_references(self):
        response = self.client.get(reverse("repairs:paystack_callback"), {
            "reference": "reference-one",
            "trxref": "reference-two",
        })
        self.assertEqual(response.status_code, 400)

    def test_verified_success_cannot_pay_a_cancelled_repair(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        RepairRequest.objects.filter(pk=repair.pk).update(status=RepairRequest.Status.CANCELLED)

        matched = record_verified_transaction(payment.pk, {
            "reference": payment.reference,
            "status": "success",
            "amount": 42000,
            "currency": "GHS",
        })

        payment.refresh_from_db()
        repair.refresh_from_db()
        self.assertFalse(matched)
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)
        self.assertEqual(repair.status, RepairRequest.Status.CANCELLED)

    def test_webhook_url_is_csrf_exempt_and_repairs_owned(self):
        endpoint = reverse("repairs:paystack_webhook")
        self.assertEqual(endpoint, "/repairs/payments/paystack/webhook/")
        self.assertEqual(resolve(endpoint).view_name, "repairs:paystack_webhook")
        self.assertTrue(getattr(resolve(endpoint).func, "csrf_exempt", False))

    def test_webhook_rejects_invalid_signature(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        raw_payload, _ = self.signed_payload(self.successful_webhook_payload(payment))

        response = self.client.post(
            reverse("repairs:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE="invalid",
        )

        self.assertEqual(response.status_code, 401)
        payment.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)

    def test_webhook_acknowledges_unhandled_events_without_changing_payment(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        raw_payload, signature = self.signed_payload({"event": "transfer.success", "data": {}})

        response = self.client.post(
            reverse("repairs:paystack_webhook"),
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(response.status_code, 200)
        payment.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)

    def test_webhook_rejects_unknown_reference_amount_and_currency(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        cases = (
            (self.successful_webhook_payload(payment, reference="unknown-reference"), 404),
            (self.successful_webhook_payload(payment, amount=41999), 400),
            (self.successful_webhook_payload(payment, currency="USD"), 400),
        )
        for payload, expected_status in cases:
            with self.subTest(payload=payload):
                raw_payload, signature = self.signed_payload(payload)
                response = self.client.post(
                    reverse("repairs:paystack_webhook"),
                    data=raw_payload,
                    content_type="application/json",
                    HTTP_X_PAYSTACK_SIGNATURE=signature,
                )
                self.assertEqual(response.status_code, expected_status)
                payment.refresh_from_db()
                self.assertEqual(payment.status, RepairPayment.Status.PENDING)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_duplicate_success_webhooks_are_idempotent(self, send_mail):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        raw_payload, signature = self.signed_payload(self.successful_webhook_payload(payment))
        endpoint = reverse("repairs:paystack_webhook")

        with self.captureOnCommitCallbacks(execute=True):
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
        repair.refresh_from_db()
        self.assertEqual(RepairPayment.objects.filter(repair_request=repair).count(), 1)
        self.assertEqual(payment.status, RepairPayment.Status.PAID)
        self.assertEqual(repair.status, RepairRequest.Status.PAID)
        self.assertEqual(repair.status_history.filter(status=RepairRequest.Status.PAID).count(), 1)
        self.assertEqual(
            RepairNotification.objects.filter(
                repair=repair,
                event="payment_received",
                channel=RepairNotification.Channel.EMAIL,
            ).count(),
            1,
        )
        self.assertEqual(
            RepairNotification.objects.get(repair=repair, event="payment_received").status,
            RepairNotification.Status.SENT,
        )
        send_mail.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", side_effect=RuntimeError("email provider unavailable"))
    def test_payment_notification_failure_preserves_verified_states(self, send_mail):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)

        with self.captureOnCommitCallbacks(execute=True):
            matched = record_verified_transaction(payment.pk, {
                "reference": payment.reference,
                "status": "success",
                "amount": 42000,
                "currency": "GHS",
                "id": 222,
            })

        payment.refresh_from_db()
        repair.refresh_from_db()
        notification = RepairNotification.objects.get(repair=repair, event="payment_received")
        self.assertTrue(matched)
        self.assertEqual(payment.status, RepairPayment.Status.PAID)
        self.assertEqual(repair.status, RepairRequest.Status.PAID)
        self.assertEqual(notification.status, RepairNotification.Status.FAILED)
        self.assertEqual(notification.error_message, "email provider unavailable")
        send_mail.assert_called_once()

    def test_duplicate_success_webhook_is_acknowledged_after_repair_progresses(self):
        repair = self.make_repair()
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        raw_payload, signature = self.signed_payload(self.successful_webhook_payload(payment))
        endpoint = reverse("repairs:paystack_webhook")
        first = self.client.post(
            endpoint,
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )
        repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)

        replay = self.client.post(
            endpoint,
            data=raw_payload,
            content_type="application/json",
            HTTP_X_PAYSTACK_SIGNATURE=signature,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(replay.status_code, 200)
        payment.refresh_from_db()
        repair.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PAID)
        self.assertEqual(repair.status, RepairRequest.Status.REPAIR_IN_PROGRESS)
        self.assertEqual(repair.status_history.filter(status=RepairRequest.Status.PAID).count(), 1)

    def test_detail_page_shows_full_payment_and_request_only_message(self):
        fixed_repair = self.make_repair()
        fixed_response = self.client.get(reverse("repairs:repair_detail", args=[fixed_repair.reference]))
        self.assertContains(fixed_response, "Fix broken screen")
        self.assertContains(fixed_response, "iPhone 15")
        self.assertContains(fixed_response, "Pay GH₵ 420.00")
        self.assertNotContains(fixed_response, "deposit")

        request_only = self.make_repair(
            request_type=RepairRequest.RequestType.ACCESSORIES_ELECTRONICS,
            service=None,
            phone_model=None,
            phone_type="",
            confirmed_price=None,
            status=RepairRequest.Status.REQUESTED,
        )
        response = self.client.get(reverse("repairs:repair_detail", args=[request_only.reference]))
        self.assertContains(response, "Payment is not required for this repair request yet.")
        self.assertNotContains(response, reverse("repairs:paystack_initialize", args=[request_only.reference]))