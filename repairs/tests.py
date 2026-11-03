from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.test import RequestFactory
from django.urls import reverse

from .models import (
    PhoneModel,
    PhoneRepairPrice,
    PhoneRepairService,
    RepairNote,
    RepairNotification,
    RepairPayment,
    RepairRequest,
    RepairStatusHistory,
)


class RepairFoundationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.iphone = PhoneModel.objects.create(
            brand="Apple",
            model_name="iPhone 13",
            phone_type=PhoneModel.PhoneType.IPHONE,
        )
        cls.android = PhoneModel.objects.create(
            brand="Samsung",
            model_name="Galaxy S25 Ultra",
            phone_type=PhoneModel.PhoneType.ANDROID,
        )
        cls.screen_service = PhoneRepairService.objects.get(name="Fix broken screen")
        cls.special_problem = PhoneRepairService.objects.get(name="Special problem")
        cls.screen_price = PhoneRepairPrice.objects.create(
            service=cls.screen_service,
            phone_model=cls.iphone,
            price=Decimal("420.00"),
            active=True,
        )

    def test_phone_model_requires_unique_brand_type_and_name(self):
        with self.assertRaises(IntegrityError):
            PhoneModel.objects.create(
                brand="Apple",
                model_name="iPhone 13",
                phone_type=PhoneModel.PhoneType.IPHONE,
            )

    def test_phone_model_string_representation(self):
        self.assertEqual(
            str(self.iphone),
            "iPhone → Apple → iPhone 13",
        )
        self.assertEqual(
            str(self.android),
            "Android → Samsung → Galaxy S25 Ultra",
        )

    def test_phone_repair_service_slug_is_unique(self):
        with self.assertRaises(IntegrityError):
            PhoneRepairService.objects.create(
                name="Fix broken screen duplicate",
                slug="fix-broken-screen",
                priceable=True,
            )

    def test_initial_phone_repair_services_are_seeded(self):
        service_names = {
            service.name for service in PhoneRepairService.objects.all()
        }
        self.assertSetEqual(
            service_names,
            {
                "Fix broken screen",
                "Change screen",
                "Fix charging system",
                "Repair speaker",
                "Change housing / backglass",
                "Special problem",
            },
        )

    def test_first_five_service_types_are_priceable_and_special_problem_is_not(self):
        self.assertTrue(PhoneRepairService.objects.get(name="Fix broken screen").priceable)
        self.assertTrue(PhoneRepairService.objects.get(name="Change screen").priceable)
        self.assertTrue(PhoneRepairService.objects.get(name="Fix charging system").priceable)
        self.assertTrue(PhoneRepairService.objects.get(name="Repair speaker").priceable)
        self.assertTrue(PhoneRepairService.objects.get(name="Change housing / backglass").priceable)
        self.assertFalse(PhoneRepairService.objects.get(name="Special problem").priceable)

    def test_phone_repair_price_requires_positive_price(self):
        with self.assertRaises(ValidationError):
            invalid = PhoneRepairPrice(
                service=self.screen_service,
                phone_model=self.android,
                price=Decimal("0.00"),
            )
            invalid.full_clean()

    def test_duplicate_service_phone_model_price_is_prevented(self):
        with self.assertRaises(IntegrityError):
            PhoneRepairPrice.objects.create(
                service=self.screen_service,
                phone_model=self.iphone,
                price=Decimal("430.00"),
                active=True,
            )

    def test_repair_request_generates_a_unique_reference(self):
        request = RepairRequest.objects.create(
            request_type=RepairRequest.RequestType.PHONE_SPECIAL_PROBLEM,
            customer_name="Ada Mensah",
            phone_number="0240000000",
            whatsapp_number="0240000000",
            guest_session_id="session-123",
        )
        self.assertTrue(request.reference.startswith("RP-"))
        self.assertEqual(request.reference, RepairRequest.objects.get(pk=request.pk).reference)

    def test_repair_request_supports_all_request_types(self):
        for request_type in (
            RepairRequest.RequestType.PHONE_SPECIAL_PROBLEM,
            RepairRequest.RequestType.LAPTOP,
            RepairRequest.RequestType.ACCESSORIES_ELECTRONICS,
        ):
            with self.subTest(request_type=request_type):
                request = RepairRequest.objects.create(
                    request_type=request_type,
                    customer_name="Test User",
                    phone_number="0241234567",
                    guest_session_id=f"guest-{request_type}",
                )
                self.assertEqual(request.request_type, request_type)

    def test_repair_status_history_belongs_to_the_correct_request(self):
        request = RepairRequest.objects.create(
            request_type=RepairRequest.RequestType.LAPTOP,
            customer_name="John Doe",
            phone_number="0241111111",
            guest_session_id="session-abc",
        )
        history = RepairStatusHistory.objects.create(
            repair_request=request,
            status=RepairRequest.Status.REQUESTED,
            note="Logged.",
        )
        self.assertEqual(history.repair_request, request)
        self.assertEqual(history.repair_request.reference, request.reference)

    def test_repair_request_uses_guest_session_ownership_not_user(self):
        request = RepairRequest.objects.create(
            request_type=RepairRequest.RequestType.ACCESSORIES_ELECTRONICS,
            customer_name="Guest User",
            phone_number="0245555555",
            guest_session_id="guest-session-42",
        )
        self.assertEqual(request.guest_session_id, "guest-session-42")
        self.assertFalse(hasattr(request, "user"))

    def test_no_deposit_or_balance_payment_fields_are_present(self):
        request_fields = {field.name for field in RepairRequest._meta.get_fields()}
        self.assertNotIn("deposit_percentage", request_fields)
        self.assertNotIn("deposit_amount", request_fields)
        self.assertNotIn("balance_amount", request_fields)

    def test_phone_model_phone_types_are_supported(self):
        self.assertEqual(PhoneModel.PhoneType.IPHONE, "IPHONE")
        self.assertEqual(PhoneModel.PhoneType.ANDROID, "ANDROID")


class RepairStudentExperienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = PhoneRepairService.objects.get(name="Fix broken screen")
        cls.inactive_service = PhoneRepairService.objects.create(
            name="Inactive service",
            slug="inactive-service",
            priceable=True,
            active=False,
        )
        cls.iphone = PhoneModel.objects.create(
            brand="Apple",
            model_name="iPhone 13",
            phone_type=PhoneModel.PhoneType.IPHONE,
            active=True,
        )
        cls.android_model = PhoneModel.objects.create(
            brand="Samsung",
            model_name="Galaxy S25 Ultra",
            phone_type=PhoneModel.PhoneType.ANDROID,
            active=True,
        )
        cls.inactive_model = PhoneModel.objects.create(
            brand="Samsung",
            model_name="Galaxy A10",
            phone_type=PhoneModel.PhoneType.ANDROID,
            active=False,
        )
        cls.price = PhoneRepairPrice.objects.create(
            service=cls.service,
            phone_model=cls.iphone,
            price=Decimal("420.00"),
            active=True,
        )
        cls.android_price = PhoneRepairPrice.objects.create(
            service=cls.service,
            phone_model=cls.android_model,
            price=Decimal("520.00"),
            active=True,
        )
        cls.inactive_price = PhoneRepairPrice.objects.create(
            service=cls.service,
            phone_model=cls.inactive_model,
            price=Decimal("300.00"),
            active=False,
        )

    def test_repairs_landing_page_loads_and_shows_only_active_services(self):
        response = self.client.get(reverse("repairs:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Phone Repairs")
        self.assertContains(response, "Laptop Repairs")
        self.assertContains(response, "Accessories & Electronics Repair")
        self.assertContains(response, "Fix broken screen")
        self.assertNotContains(response, "Inactive service")

    def test_request_only_services_link_to_the_special_request_form(self):
        custom = PhoneRepairService.objects.create(name="Custom phone repair", slug="custom-phone-repair", priceable=True)
        response = self.client.get(reverse("repairs:home"))
        special = PhoneRepairService.objects.get(slug="special-problem")
        for service in (special, custom):
            with self.subTest(service=service.slug):
                self.assertContains(response, service.name)
                self.assertNotContains(response, reverse("repairs:phone_service", args=[service.slug]))
        self.assertContains(response, f'href="{reverse("repairs:special_phone_request")}"', count=2)
        self.assertEqual(self.client.get(reverse("repairs:special_phone_request")).status_code, 200)
        self.assertContains(response, f'href="{reverse("repairs:phone_service", args=[self.service.slug])}"')

        self.service.priceable = False
        self.service.save()
        response = self.client.get(reverse("repairs:home"))
        self.assertNotContains(response, reverse("repairs:phone_service", args=[self.service.slug]))

    def test_phone_repairs_category_remains_usable_when_screen_service_is_inactive(self):
        self.service.active = False
        self.service.save()
        response = self.client.get(reverse("repairs:home"))
        self.assertContains(response, 'href="#phone-services"')
        self.assertContains(response, 'id="phone-services"')
        self.assertNotContains(response, reverse("repairs:phone_service", args=[self.service.slug]))
        self.assertContains(response, reverse("repairs:special_phone_request"))

    def test_phone_service_page_rejects_invalid_and_inactive_services(self):
        invalid = self.client.get(reverse("repairs:phone_service", args=["missing-service"]))
        self.assertEqual(invalid.status_code, 404)
        inactive = self.client.get(reverse("repairs:phone_service", args=[self.inactive_service.slug]))
        self.assertEqual(inactive.status_code, 404)

    def test_phone_type_and_model_selection_filters_by_device_type(self):
        response = self.client.get(reverse("repairs:phone_service", args=[self.service.slug]), {"phone_type": PhoneModel.PhoneType.IPHONE})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "iPhone 13")
        self.assertNotContains(response, "Galaxy S25 Ultra")

        response = self.client.get(reverse("repairs:phone_service", args=[self.service.slug]), {"phone_type": PhoneModel.PhoneType.ANDROID})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Samsung")
        self.assertContains(response, "Galaxy S25 Ultra")
        self.assertNotContains(response, "iPhone 13")

    def test_inactive_models_are_not_selectable(self):
        response = self.client.get(reverse("repairs:phone_service", args=[self.service.slug]), {"phone_type": PhoneModel.PhoneType.ANDROID, "phone_model": self.inactive_model.pk})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No models are currently available")

    def test_server_side_price_lookup_returns_the_db_price_and_rejects_fake_client_values(self):
        response = self.client.post(
            reverse("repairs:phone_service", args=[self.service.slug]),
            {
                "phone_type": PhoneModel.PhoneType.IPHONE,
                "phone_model": self.iphone.pk,
                "fake_price": "999.99",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GH₵ 420.00")
        self.assertNotContains(response, "999.99")

        response = self.client.post(
            reverse("repairs:phone_service", args=[self.service.slug]),
            {
                "phone_type": PhoneModel.PhoneType.IPHONE,
                "phone_model": self.iphone.pk,
                "fake_price": "0.00",
            },
        )
        self.assertContains(response, "GH₵ 420.00")

    def test_inactive_price_is_rejected(self):
        response = self.client.post(
            reverse("repairs:phone_service", args=[self.service.slug]),
            {
                "phone_type": PhoneModel.PhoneType.ANDROID,
                "phone_model": self.inactive_model.pk,
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No models are currently available")

    def test_special_phone_request_creates_request_and_initial_status(self):
        session = self.client.session
        session["repair_guest_session_id"] = "session-special"
        session.save()
        response = self.client.post(
            reverse("repairs:special_phone_request"),
            {
                "phone_type": PhoneModel.PhoneType.IPHONE,
                "phone_model": self.iphone.pk,
                "problem_description": "Camera not working",
                "name": "Amina",
                "phone_number": "0240000000",
                "whatsapp_number": "0240000000",
                "email": "amina@example.com",
                "preferred_contact_method": "WhatsApp",
                "customer_note": "Please call after 3pm",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "submitted successfully")
        request = RepairRequest.objects.get(customer_name="Amina")
        self.assertEqual(request.guest_session_id, "session-special")
        self.assertTrue(request.status_history.exists())
        self.assertEqual(request.status_history.first().status, RepairRequest.Status.REQUESTED)

    def test_laptop_and_electronics_requests_create_status_history(self):
        for url, payload in (
            (
                reverse("repairs:laptop_request"),
                {
                    "name": "Kofi",
                    "phone_number": "0241111111",
                    "whatsapp_number": "0241111111",
                    "email": "kofi@example.com",
                    "brand": "Dell",
                    "problem_description": "Battery issue",
                    "preferred_contact_method": "Phone",
                },
            ),
            (
                reverse("repairs:electronics_request"),
                {
                    "name": "Efua",
                    "phone_number": "0242222222",
                    "whatsapp_number": "0242222222",
                    "email": "efua@example.com",
                    "item_description": "Power bank",
                    "problem_description": "Charging intermittently",
                    "preferred_contact_method": "WhatsApp",
                },
            ),
        ):
            with self.subTest(url=url):
                self.client.session["repair_guest_session_id"] = f"session-{url.split('/')[-2]}"
                self.client.session.save()
                response = self.client.post(url, payload)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "submitted successfully")
                request = RepairRequest.objects.latest("pk")
                self.assertTrue(request.status_history.exists())

    def test_student_can_view_own_repair_and_cannot_view_another_session_repair(self):
        request = RepairRequest.objects.create(
            request_type=RepairRequest.RequestType.LAPTOP,
            customer_name="Random",
            phone_number="0243333333",
            guest_session_id="session-owner",
        )
        response = self.client.get(reverse("repairs:repair_detail", args=[request.reference]))
        self.assertEqual(response.status_code, 404)

        session = self.client.session
        session["repair_guest_session_id"] = "session-owner"
        session.save()
        response = self.client.get(reverse("repairs:repair_detail", args=[request.reference]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, request.reference)
        self.assertContains(response, "Under review")

    def test_no_paystack_or_deposit_logic_in_repairs_views(self):
        response = self.client.get(reverse("repairs:home"))
        self.assertNotContains(response, "Paystack")
        self.assertNotContains(response, "deposit")
        self.assertNotContains(response, "balance")


class RepairOperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = PhoneRepairService.objects.get(slug="fix-broken-screen")
        cls.phone_model = PhoneModel.objects.create(
            brand="Apple",
            model_name="iPhone 14",
            phone_type=PhoneModel.PhoneType.IPHONE,
        )
        cls.price = PhoneRepairPrice.objects.create(
            service=cls.service,
            phone_model=cls.phone_model,
            price=Decimal("400.00"),
        )

    def make_repair(self, request_type=RepairRequest.RequestType.LAPTOP, **overrides):
        values = {
            "request_type": request_type,
            "customer_name": "Kojo Mensah",
            "phone_number": "0241111111",
            "description": "Device will not start.",
            "guest_session_id": "repair-ops-session",
        }
        if request_type == RepairRequest.RequestType.FIXED_PRICE_PHONE:
            values.update({
                "phone_type": self.phone_model.phone_type,
                "phone_model": self.phone_model,
                "service": self.service,
                "confirmed_price": self.price.price,
                "status": RepairRequest.Status.PRICE_CONFIRMED,
            })
        values.update(overrides)
        return RepairRequest.objects.create(**values)

    def test_valid_status_transitions_append_history_and_repeats_are_idempotent(self):
        repair = self.make_repair()

        self.assertTrue(repair.transition_to(RepairRequest.Status.UNDER_REVIEW, note="Checked in."))
        self.assertFalse(repair.transition_to(RepairRequest.Status.UNDER_REVIEW, note="Duplicate."))
        self.assertTrue(repair.transition_to(RepairRequest.Status.CONTACTED, note="Called customer."))

        repair.refresh_from_db()
        history = list(repair.status_history.all())
        self.assertEqual(repair.status, RepairRequest.Status.CONTACTED)
        self.assertEqual([item.status for item in history], [
            RepairRequest.Status.UNDER_REVIEW,
            RepairRequest.Status.CONTACTED,
        ])
        self.assertEqual(history[0].note, "Checked in.")
        self.assertEqual(history[1].note, "Called customer.")

    def test_invalid_transition_and_direct_status_save_are_rejected(self):
        repair = self.make_repair()

        with self.assertRaises(ValidationError):
            repair.transition_to(RepairRequest.Status.COMPLETED)
        repair.refresh_from_db()
        self.assertEqual(repair.status, RepairRequest.Status.REQUESTED)
        self.assertFalse(repair.status_history.exists())

        repair.status = RepairRequest.Status.COMPLETED
        with self.assertRaises(ValidationError):
            repair.save(update_fields={"status"})

    def test_fixed_price_repair_cannot_start_work_or_complete_without_payment(self):
        repair = self.make_repair(RepairRequest.RequestType.FIXED_PRICE_PHONE)

        with self.assertRaises(ValidationError):
            repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)
        with self.assertRaises(ValidationError):
            repair.transition_to(RepairRequest.Status.COMPLETED)
        with self.assertRaises(ValidationError):
            repair.transition_to(RepairRequest.Status.PAYMENT_PENDING)
        self.assertEqual(repair.status, RepairRequest.Status.PRICE_CONFIRMED)

    def test_payment_and_repair_status_are_separate_and_paid_does_not_complete(self):
        from .payments import create_payment_attempt, record_verified_transaction

        repair = self.make_repair(
            RepairRequest.RequestType.FIXED_PRICE_PHONE,
            email="kojo@example.test",
        )
        payment, _ = create_payment_attempt(repair.pk, repair.email)
        self.assertEqual(payment.status, RepairPayment.Status.PENDING)
        repair.refresh_from_db()
        self.assertEqual(repair.status, RepairRequest.Status.PAYMENT_PENDING)

        self.assertTrue(record_verified_transaction(payment.pk, {
            "reference": payment.reference,
            "status": "success",
            "amount": 40000,
            "currency": "GHS",
            "id": 4001,
        }))

        payment.refresh_from_db()
        repair.refresh_from_db()
        self.assertEqual(payment.status, RepairPayment.Status.PAID)
        self.assertEqual(repair.status, RepairRequest.Status.PAID)
        self.assertNotEqual(repair.status, RepairRequest.Status.COMPLETED)
        self.assertEqual(repair.status_history.filter(status=RepairRequest.Status.PAID).count(), 1)

    def test_internal_notes_are_visible_in_admin_but_not_student_pages(self):
        repair = self.make_repair()
        note_text = "INTERNAL: supplier diagnostic pending; do not share with customer."
        RepairNote.objects.create(repair_request=repair, note=note_text)

        session = self.client.session
        session["repair_guest_session_id"] = repair.guest_session_id
        session.save()
        public_response = self.client.get(reverse("repairs:repair_detail", args=[repair.reference]))
        self.assertEqual(public_response.status_code, 200)
        self.assertNotContains(public_response, note_text)

        admin_user = get_user_model().objects.create_superuser(
            username="repairs-ops-admin",
            email="repairs-ops@example.test",
            password=None,
        )
        admin_client = self.client_class()
        admin_client.force_login(admin_user)
        admin_response = admin_client.get(
            reverse("admin:repairs_repairrequest_change", args=[repair.pk])
        )
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, note_text)
        self.assertContains(admin_response, "Repair status histories")
        self.assertContains(admin_response, "Repair payments")

    def test_repair_admin_has_operational_columns_search_filters_and_inlines(self):
        repair = self.make_repair()
        admin_user = get_user_model().objects.create_superuser(
            username="repairs-list-admin",
            email="repairs-list@example.test",
            password=None,
        )
        self.client.force_login(admin_user)

        response = self.client.get(reverse("admin:repairs_repairrequest_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, repair.reference)
        repair_admin = admin.site._registry[RepairRequest]
        self.assertIn("customer_name", repair_admin.search_fields)
        self.assertIn("status", repair_admin.list_filter)
        self.assertEqual(len(repair_admin.inlines), 4)

    def test_admin_payment_and_notification_records_are_readonly(self):
        payment_admin = admin.site._registry[RepairPayment]
        notification_admin = admin.site._registry[RepairNotification]
        self.assertSetEqual(
            set(payment_admin.readonly_fields),
            {field.name for field in RepairPayment._meta.fields},
        )
        self.assertSetEqual(
            set(notification_admin.readonly_fields),
            {field.name for field in RepairNotification._meta.fields},
        )

    def test_admin_status_change_uses_transition_validation_and_audit_note(self):
        repair = self.make_repair()
        admin_user = get_user_model().objects.create_superuser(
            username="repairs-transition-admin",
            email="repairs-transition@example.test",
            password=None,
        )
        request = RequestFactory().post("/")
        request.user = admin_user
        form = SimpleNamespace(
            initial={"status": repair.status},
            cleaned_data={"status_note": "Device received for inspection."},
        )
        repair.status = RepairRequest.Status.UNDER_REVIEW

        admin.site._registry[RepairRequest].save_model(request, repair, form, change=True)

        repair.refresh_from_db()
        history = repair.status_history.get()
        self.assertEqual(repair.status, RepairRequest.Status.UNDER_REVIEW)
        self.assertEqual(history.status, RepairRequest.Status.UNDER_REVIEW)
        self.assertEqual(history.note, "Device received for inspection.")


class RepairNotificationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.service = PhoneRepairService.objects.get(slug="fix-broken-screen")
        cls.phone_model = PhoneModel.objects.create(
            brand="Apple",
            model_name="iPhone 12",
            phone_type=PhoneModel.PhoneType.IPHONE,
        )

    def make_repair(self, **overrides):
        values = {
            "request_type": RepairRequest.RequestType.LAPTOP,
            "customer_name": "Akosua Owusu",
            "phone_number": "0242222222",
            "email": "akosua@example.test",
            "description": "Device will not start.",
            "guest_session_id": "notification-session",
        }
        values.update(overrides)
        return RepairRequest.objects.create(**values)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_request_creates_and_sends_customer_email(self, send_mail):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("repairs:laptop_request"),
                {
                    "name": "Akosua Owusu",
                    "phone_number": "0242222222",
                    "email": "akosua@example.test",
                    "brand": "Dell",
                    "problem_description": "Won't power on",
                },
            )

        self.assertEqual(response.status_code, 200)
        repair = RepairRequest.objects.get(customer_name="Akosua Owusu")
        notification = RepairNotification.objects.get(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event="repair_request_received",
        )
        self.assertEqual(notification.recipient, "akosua@example.test")
        self.assertEqual(notification.status, RepairNotification.Status.SENT)
        self.assertIsNotNone(notification.sent_at)
        self.assertIn(repair.reference, notification.message)
        send_mail.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_status_notifications_are_meaningful_and_duplicate_event_is_idempotent(self, send_mail):
        from .notifications import create_notification_for_status

        repair = self.make_repair()
        with self.captureOnCommitCallbacks(execute=True):
            repair.transition_to(RepairRequest.Status.UNDER_REVIEW)
            repair.transition_to(RepairRequest.Status.CONTACTED)
            repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)
            create_notification_for_status(repair)
            create_notification_for_status(repair)

        self.assertEqual(RepairNotification.objects.filter(repair=repair).count(), 1)
        notification = RepairNotification.objects.get(repair=repair)
        self.assertEqual(notification.event, "repair_in_progress")
        self.assertEqual(notification.status, RepairNotification.Status.SENT)
        send_mail.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", side_effect=RuntimeError("provider unavailable"))
    def test_delivery_failure_is_recorded_without_changing_repair_status(self, send_mail):
        repair = self.make_repair()
        with self.captureOnCommitCallbacks(execute=True):
            repair.transition_to(RepairRequest.Status.UNDER_REVIEW)
            repair.transition_to(RepairRequest.Status.CONTACTED)
            repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)
            repair.transition_to(RepairRequest.Status.READY)

        repair.refresh_from_db()
        notification = RepairNotification.objects.get(repair=repair, event="repair_ready")
        self.assertEqual(repair.status, RepairRequest.Status.READY)
        self.assertEqual(notification.status, RepairNotification.Status.FAILED)
        self.assertEqual(notification.error_message, "provider unavailable")
        self.assertIsNone(notification.sent_at)
        send_mail.assert_called()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_customer_message_never_contains_internal_notes(self, send_mail):
        from .notifications import create_notification_for_status

        repair = self.make_repair()
        internal_text = "Supplier delay. Call technician before customer."
        RepairNote.objects.create(repair_request=repair, note=internal_text)
        with self.captureOnCommitCallbacks(execute=True):
            repair.transition_to(RepairRequest.Status.UNDER_REVIEW)
            repair.transition_to(RepairRequest.Status.CONTACTED)
            repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)
            repair.transition_to(RepairRequest.Status.READY)
            notification = create_notification_for_status(repair)

        notification = RepairNotification.objects.get(repair=repair, event="repair_ready")
        self.assertNotIn(internal_text, notification.message)
        self.assertNotIn("Paystack", notification.message)
        self.assertNotIn("provider", notification.message.lower())

    def test_missing_email_creates_no_notification(self):
        from .notifications import create_notification_for_status

        repair = self.make_repair(email="")
        with self.captureOnCommitCallbacks(execute=True):
            repair.transition_to(RepairRequest.Status.UNDER_REVIEW)
            repair.transition_to(RepairRequest.Status.CONTACTED)
            repair.transition_to(RepairRequest.Status.REPAIR_IN_PROGRESS)
            repair.transition_to(RepairRequest.Status.READY)
            create_notification_for_status(repair)
        self.assertFalse(RepairNotification.objects.filter(repair=repair).exists())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_failed_notification_retry_sends_once_and_sent_retry_is_noop(self, send_mail):
        from .notifications import retry_notification

        repair = self.make_repair()
        notification = RepairNotification.objects.create(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event="repair_ready",
            recipient=repair.email,
            subject="Ready",
            message="Your repair is ready.",
            status=RepairNotification.Status.FAILED,
            error_message="Previous delivery failed.",
        )

        self.assertTrue(retry_notification(notification))
        self.assertFalse(retry_notification(notification))

        notification.refresh_from_db()
        self.assertEqual(notification.status, RepairNotification.Status.SENT)
        self.assertEqual(RepairNotification.objects.filter(repair=repair).count(), 1)
        send_mail.assert_called_once()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_malformed_email_is_recorded_failed_not_sent(self, send_mail):
        from .notifications import create_notification_for_status

        repair = self.make_repair(email="not-an-email")
        with self.captureOnCommitCallbacks(execute=True):
            create_notification_for_status(repair)

        notification = RepairNotification.objects.get(repair=repair)
        self.assertEqual(notification.status, RepairNotification.Status.FAILED)
        self.assertIn("valid", notification.error_message.lower())
        self.assertIsNone(notification.sent_at)
        send_mail.assert_not_called()

    @patch("repairs.notifications.send_mail", return_value=1)
    def test_blank_smtp_configuration_never_records_sent(self, send_mail):
        from .notifications import create_notification_for_status

        repair = self.make_repair()
        with override_settings(
            EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
            EMAIL_HOST="",
            DEFAULT_FROM_EMAIL="",
        ), self.captureOnCommitCallbacks(execute=True):
            create_notification_for_status(repair)

        notification = RepairNotification.objects.get(repair=repair)
        self.assertEqual(notification.status, RepairNotification.Status.FAILED)
        self.assertIn("not configured", notification.error_message.lower())
        send_mail.assert_not_called()

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_notification_recipient_is_taken_from_its_own_repair(self, send_mail):
        from .notifications import create_notification_for_status

        repair_one = self.make_repair(email="one@example.test")
        repair_two = self.make_repair(email="two@example.test", guest_session_id="other-session")
        with self.captureOnCommitCallbacks(execute=True):
            create_notification_for_status(repair_one)
            create_notification_for_status(repair_two)

        recipients = set(
            RepairNotification.objects.values_list("recipient", flat=True)
        )
        self.assertSetEqual(recipients, {"one@example.test", "two@example.test"})
        self.assertEqual(send_mail.call_count, 2)
        self.assertCountEqual(
            [call.kwargs["recipient_list"][0] for call in send_mail.call_args_list],
            ["one@example.test", "two@example.test"],
        )

    def test_admin_can_inspect_and_retry_failed_notification(self):
        repair = self.make_repair()
        notification = RepairNotification.objects.create(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event="repair_ready",
            recipient=repair.email,
            subject="Your repair is ready",
            message="Your repair is ready.",
            status=RepairNotification.Status.FAILED,
            error_message="Provider unavailable.",
        )
        admin_user = get_user_model().objects.create_superuser(
            username="notification-admin",
            email="notification-admin@example.test",
            password=None,
        )
        self.client.force_login(admin_user)
        response = self.client.get(reverse("admin:repairs_repairnotification_change", args=[notification.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Provider unavailable.")
        self.assertIn("retry_failed_notifications", admin.site._registry[RepairNotification].actions)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
        EMAIL_HOST="smtp.example.test",
        DEFAULT_FROM_EMAIL="repairs@example.test",
    )
    @patch("repairs.notifications.send_mail", return_value=1)
    def test_admin_retry_sends_failed_notification_without_changing_repair(self, send_mail):
        repair = self.make_repair()
        notification = RepairNotification.objects.create(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event="repair_ready",
            recipient=repair.email,
            subject="Your repair is ready",
            message="Your repair is ready.",
            status=RepairNotification.Status.FAILED,
            error_message="Provider unavailable.",
        )
        admin_user = get_user_model().objects.create_superuser(
            username="notification-retry-admin",
            email="notification-retry@example.test",
            password=None,
        )
        self.client.force_login(admin_user)

        response = self.client.post(reverse("admin:repairs_repairnotification_changelist"), {
            "action": "retry_failed_notifications",
            "_selected_action": [str(notification.pk)],
        })

        self.assertEqual(response.status_code, 302)
        notification.refresh_from_db()
        repair.refresh_from_db()
        self.assertEqual(notification.status, RepairNotification.Status.SENT)
        self.assertEqual(notification.error_message, "")
        self.assertEqual(repair.status, RepairRequest.Status.REQUESTED)
        send_mail.assert_called_once()

    def test_student_repair_page_hides_notification_failure_and_provider_details(self):
        repair = self.make_repair()
        RepairNotification.objects.create(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event="repair_request_received",
            recipient=repair.email,
            subject="Repair received",
            message="Customer safe message.",
            status=RepairNotification.Status.FAILED,
            provider_reference="private-provider-reference",
            error_message="private delivery failure detail",
        )
        session = self.client.session
        session["repair_guest_session_id"] = repair.guest_session_id
        session.save()

        response = self.client.get(reverse("repairs:repair_detail", args=[repair.reference]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "private-provider-reference")
        self.assertNotContains(response, "private delivery failure detail")
