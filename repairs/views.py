import hashlib
import hmac
import json
import logging
import uuid

from django.conf import settings
from django.core import validators
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.db import transaction
from django.http import Http404, HttpResponse
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from orders.payments import paystack_is_enabled

from .models import (
    PhoneModel,
    PhoneRepairPrice,
    PhoneRepairService,
    RepairRequest,
    RepairStatusHistory,
    RepairPayment,
)
from .notifications import create_notification_for_status
from .payments import (
    FIXED_PRICE_SERVICE_SLUGS,
    PaystackError,
    RepairPaymentError,
    RepairPriceChanged,
    amount_in_subunits,
    create_payment_attempt,
    current_repair_price,
    initialize_transaction,
    mark_initialization_failed,
    record_verified_transaction,
    validate_paystack_configuration,
    verify_transaction,
)

SESSION_GUEST_KEY = "repair_guest_session_id"
logger = logging.getLogger(__name__)


def get_or_create_guest_session_id(request):
    guest_id = request.session.get(SESSION_GUEST_KEY)
    if not guest_id:
        guest_id = str(uuid.uuid4())
        request.session[SESSION_GUEST_KEY] = guest_id
    return guest_id


def _status_steps(request_type):
    if request_type == RepairRequest.RequestType.FIXED_PRICE_PHONE:
        return [
            RepairRequest.Status.PRICE_CONFIRMED,
            RepairRequest.Status.PAYMENT_PENDING,
            RepairRequest.Status.PAID,
            RepairRequest.Status.REPAIR_IN_PROGRESS,
            RepairRequest.Status.READY,
            RepairRequest.Status.COMPLETED,
        ]
    if request_type == RepairRequest.RequestType.PHONE_SPECIAL_PROBLEM:
        return [
            RepairRequest.Status.REQUESTED,
            RepairRequest.Status.UNDER_REVIEW,
            RepairRequest.Status.CONTACTED,
            RepairRequest.Status.PRICE_CONFIRMED,
            RepairRequest.Status.REPAIR_IN_PROGRESS,
            RepairRequest.Status.READY,
            RepairRequest.Status.COMPLETED,
        ]
    return [
        RepairRequest.Status.REQUESTED,
        RepairRequest.Status.UNDER_REVIEW,
        RepairRequest.Status.CONTACTED,
        RepairRequest.Status.REPAIR_IN_PROGRESS,
        RepairRequest.Status.READY,
        RepairRequest.Status.COMPLETED,
    ]


def home(request):
    services = PhoneRepairService.objects.filter(active=True).order_by("name")
    return render(request, "repairs/landing.html", {
        "services": services,
        "fixed_price_service_slugs": FIXED_PRICE_SERVICE_SLUGS,
    })


def phone_repair_service(request, service_slug):
    service = get_object_or_404(PhoneRepairService, slug=service_slug, active=True)
    if not service.priceable or service.slug not in FIXED_PRICE_SERVICE_SLUGS:
        raise Http404

    selected_phone_type = request.POST.get("phone_type") or request.GET.get("phone_type")
    selected_model_id = request.POST.get("phone_model") or request.GET.get("phone_model")
    repair_reference = request.POST.get("repair_reference") or request.GET.get("repair_reference", "")
    available_models = PhoneModel.objects.none()
    selected_model = None
    price_instance = None
    price_value = None
    selected_phone_type_display = None
    error_message = None
    success_message = None

    if selected_phone_type:
        selected_phone_type_display = dict(PhoneModel.PhoneType.choices).get(selected_phone_type)
        available_models = PhoneModel.objects.filter(active=True, phone_type=selected_phone_type).order_by("brand", "model_name")
        if selected_model_id:
            selected_model = available_models.filter(pk=selected_model_id).first()
            if selected_model is None:
                error_message = "No models are currently available for this repair service. Please contact us."
            else:
                price_instance = PhoneRepairPrice.objects.filter(
                    service=service,
                    phone_model=selected_model,
                    active=True,
                ).first()
                if price_instance is None:
                    error_message = "No models are currently available for this repair service. Please contact us."
                else:
                    price_value = price_instance.price
                    if request.method == "POST" and request.POST.get("confirm_price"):
                        success_message = "Repair price confirmed. Our team will contact you to confirm the repair."

    if (
        request.method == "POST"
        and request.POST.get("confirm_price")
        and selected_phone_type
        and selected_model_id
        and price_value is not None
    ):
        name = (request.POST.get("name") or "").strip()
        phone_number = (request.POST.get("phone_number") or "").strip()
        email = (request.POST.get("email") or "").strip()
        if not name or not phone_number:
            error_message = "Enter your name and phone number to confirm this repair price."
        else:
            try:
                email = validators.validate_email(email) or email
            except ValidationError:
                error_message = "Enter a valid email address for Paystack checkout."

        if error_message:
            return render(
                request,
                "repairs/phone_service.html",
                {
                    "service": service,
                    "selected_phone_type": selected_phone_type,
                    "selected_phone_type_display": selected_phone_type_display,
                    "selected_model": selected_model,
                    "available_models": available_models,
                    "price": price_value,
                    "error_message": error_message,
                    "customer_name": name,
                    "customer_phone": phone_number,
                    "customer_email": email,
                    "repair_reference": request.POST.get("repair_reference", ""),
                },
            )

        repair_reference = repair_reference.strip()
        if repair_reference:
            with transaction.atomic():
                repair_request = get_object_or_404(
                    RepairRequest,
                    reference=repair_reference,
                    guest_session_id=request.session.get(SESSION_GUEST_KEY),
                    request_type=RepairRequest.RequestType.FIXED_PRICE_PHONE,
                    service=service,
                    phone_model=selected_model,
                )
                if repair_request.status not in {
                    RepairRequest.Status.PRICE_CONFIRMED,
                    RepairRequest.Status.PAYMENT_PENDING,
                }:
                    raise Http404("Repair price cannot be changed")
                changed = repair_request.confirmed_price != price_value
                previous_status = repair_request.status
                repair_request.customer_name = name
                repair_request.phone_number = phone_number
                repair_request.email = email
                repair_request.confirmed_price = price_value
                repair_request.save(update_fields={
                    "customer_name", "phone_number", "email", "confirmed_price", "updated_at",
                })
                if previous_status == RepairRequest.Status.PAYMENT_PENDING:
                    repair_request.transition_to(
                        RepairRequest.Status.PRICE_CONFIRMED,
                        note="Student confirmed the updated repair price.",
                    )
                elif changed:
                    RepairStatusHistory.objects.create(
                        repair_request=repair_request,
                        status=RepairRequest.Status.PRICE_CONFIRMED,
                        note="Student confirmed the updated repair price.",
                    )
        else:
            with transaction.atomic():
                repair_request = RepairRequest.objects.create(
                    request_type=RepairRequest.RequestType.FIXED_PRICE_PHONE,
                    customer_name=name,
                    phone_number=phone_number,
                    email=email,
                    guest_session_id=get_or_create_guest_session_id(request),
                    phone_type=selected_phone_type,
                    phone_model=selected_model,
                    service=service,
                    confirmed_price=price_value,
                    status=RepairRequest.Status.PRICE_CONFIRMED,
                )
                RepairStatusHistory.objects.create(
                    repair_request=repair_request,
                    status=RepairRequest.Status.PRICE_CONFIRMED,
                    note="Student confirmed the current repair price.",
                )
                create_notification_for_status(repair_request)
        return redirect("repairs:repair_detail", reference=repair_request.reference)

    if request.method == "POST" and selected_phone_type and selected_model_id and price_value is not None:
        return render(
            request,
            "repairs/phone_service.html",
            {
                "service": service,
                "selected_phone_type": selected_phone_type,
                "selected_phone_type_display": selected_phone_type_display,
                "selected_model": selected_model,
                "available_models": available_models,
                "price": price_value,
                "success_message": success_message,
                "repair_reference": repair_reference,
            },
        )

    return render(
        request,
        "repairs/phone_service.html",
        {
            "service": service,
            "selected_phone_type": selected_phone_type,
            "selected_phone_type_display": selected_phone_type_display,
            "available_models": available_models,
            "selected_model": selected_model,
            "price": price_value,
            "error_message": error_message,
            "success_message": success_message,
            "repair_reference": repair_reference,
        },
    )


def _submit_request(request, request_type, page_title, extra_fields=None, phone_models=None):
    if request.method == "POST":
        error_message = None
        name = (request.POST.get("name") or "").strip()
        phone_number = (request.POST.get("phone_number") or "").strip()
        problem_description = (request.POST.get("problem_description") or "").strip()
        preferred_contact_method = (request.POST.get("preferred_contact_method") or "").strip()
        if not name or not phone_number or not problem_description:
            error_message = "Please complete the required fields before submitting your repair request."
        elif request_type == RepairRequest.RequestType.PHONE_SPECIAL_PROBLEM and not request.POST.get("phone_type"):
            error_message = "Please choose a phone type before submitting your repair request."

        if error_message:
            return render(
                request,
                "repairs/request_form.html",
                {
                    "page_title": page_title,
                    "request_type": request_type,
                    "error_message": error_message,
                    "phone_models": phone_models or PhoneModel.objects.filter(active=True). order_by("brand", "model_name"),
                },
            )

        phone_model = None
        phone_type = request.POST.get("phone_type")
        if phone_type:
            model_id = request.POST.get("phone_model")
            if model_id:
                phone_model = get_object_or_404(
                    PhoneModel,
                    pk=model_id,
                    phone_type=phone_type,
                    active=True,
                )

        description_parts = []
        if problem_description:
            description_parts.append(problem_description)
        if preferred_contact_method:
            description_parts.append(f"Preferred contact method: {preferred_contact_method}")
        if request.POST.get("customer_note"):
            description_parts.append(f"Customer note: {request.POST.get('customer_note').strip()}")
        if extra_fields:
            for label, value in extra_fields.items():
                if value:
                    description_parts.append(f"{label}: {value}")

        repair_request = RepairRequest.objects.create(
            request_type=request_type,
            customer_name=name,
            phone_number=phone_number,
            whatsapp_number=(request.POST.get("whatsapp_number") or "").strip(),
            email=(request.POST.get("email") or "").strip(),
            description="\n\n".join(description_parts),
            status=RepairRequest.Status.REQUESTED,
            guest_session_id=get_or_create_guest_session_id(request),
            phone_type=phone_type or "",
            phone_model=phone_model,
        )
        if request.FILES.get("image"):
            repair_request.image = request.FILES["image"]
            repair_request.save(update_fields=["image"])

        RepairStatusHistory.objects.create(
            repair_request=repair_request,
            status=RepairRequest.Status.REQUESTED,
            note="Request submitted.",
        )
        create_notification_for_status(repair_request)

        return render(
            request,
            "repairs/request_form.html",
            {
                "page_title": page_title,
                "request_type": request_type,
                "message": "Your repair request has been submitted successfully. Our team will contact you by SMS, WhatsApp, or phone call to discuss the repair.",
                "phone_models": phone_models or PhoneModel.objects.filter(active=True).order_by("brand", "model_name"),
            },
        )

    return render(
        request,
        "repairs/request_form.html",
        {
            "page_title": page_title,
            "request_type": request_type,
            "phone_models": phone_models or PhoneModel.objects.filter(active=True).order_by("brand", "model_name"),
        },
    )


def special_phone_request(request):
    return _submit_request(
        request,
        RepairRequest.RequestType.PHONE_SPECIAL_PROBLEM,
        "Special phone problem",
        phone_models=PhoneModel.objects.filter(active=True).order_by("brand", "model_name"),
    )


def laptop_request(request):
    return _submit_request(
        request,
        RepairRequest.RequestType.LAPTOP,
        "Laptop repair",
        extra_fields={
            "Brand": request.POST.get("brand"),
            "Model": request.POST.get("model"),
        },
    )


def electronics_request(request):
    return _submit_request(
        request,
        RepairRequest.RequestType.ACCESSORIES_ELECTRONICS,
        "Accessories & electronics repair",
        extra_fields={
            "Item or device": request.POST.get("item_description"),
        },
    )


def repair_detail(request, reference):
    repair_request = get_object_or_404(
        RepairRequest.objects.select_related("service", "phone_model").prefetch_related("payments"),
        reference=reference,
    )
    guest_session_id = request.session.get(SESSION_GUEST_KEY)
    if repair_request.guest_session_id != guest_session_id:
        raise Http404

    status_history = repair_request.status_history.all()
    if not status_history.exists():
        status_history = [
            RepairStatusHistory.objects.create(
                repair_request=repair_request,
                status=RepairRequest.Status.REQUESTED,
                note="Request submitted.",
            )
        ]

    status_timeline = [
        {"code": status, "label": status.label}
        for status in _status_steps(repair_request.request_type)
    ]

    payments = list(repair_request.payments.all())
    latest_payment = payments[0] if payments else None
    current_price = None
    price_changed = False
    if repair_request.request_type == RepairRequest.RequestType.FIXED_PRICE_PHONE:
        try:
            current_price = current_repair_price(repair_request).price
            price_changed = current_price != repair_request.confirmed_price
        except RepairPaymentError:
            price_changed = True

    return render(
        request,
        "repairs/detail.html",
        {
            "repair_request": repair_request,
            "status_history": status_history,
            "status_timeline": status_timeline,
            "latest_payment": latest_payment,
            "current_price": current_price,
            "price_changed": price_changed,
            "paystack_enabled": paystack_is_enabled(),
        },
    )


@never_cache
@require_POST
def paystack_initialize(request, reference):
    repair_request = get_object_or_404(
        RepairRequest.objects.select_related("service", "phone_model"),
        reference=reference,
    )
    guest_session_id = request.session.get(SESSION_GUEST_KEY)
    if not guest_session_id or repair_request.guest_session_id != guest_session_id:
        raise Http404("Repair not found")
    if repair_request.request_type != RepairRequest.RequestType.FIXED_PRICE_PHONE:
        messages.info(request, "Payment is not required for this repair request yet. Our team will contact you first.")
        return redirect("repairs:repair_detail", reference=reference)

    payment = None
    try:
        if not paystack_is_enabled():
            raise PaystackError("Payment is temporarily unavailable.")
        email = repair_request.email
        validators.validate_email(email)
        payment, should_initialize = create_payment_attempt(repair_request.pk, email)
        if not should_initialize and payment.authorization_url:
            return redirect(payment.authorization_url)

        # Revalidate catalogue eligibility immediately before calling Paystack.
        repair_request.refresh_from_db()
        price = current_repair_price(repair_request)
        if price.price != payment.amount or price.price != repair_request.confirmed_price:
            raise RepairPriceChanged("The repair price has changed. Review and confirm the updated price before paying.")
        callback_url = request.build_absolute_uri(reverse("repairs:paystack_callback"))
        result = initialize_transaction(
            email=email,
            amount=payment.amount,
            reference=payment.reference,
            callback_url=callback_url,
        )
        payment.authorization_url = result["authorization_url"]
        payment.provider_response = {
            key: result.get(key)
            for key in ("reference", "status")
            if result.get(key) is not None
        }
        payment.save(update_fields={"authorization_url", "provider_response", "updated_at"})
        return redirect(payment.authorization_url)
    except RepairPriceChanged:
        if payment is not None:
            mark_initialization_failed(payment.pk)
        messages.error(request, "The repair price changed. Review the current price and confirm it again before paying.")
        return redirect(
            f"{reverse('repairs:phone_service', args=[repair_request.service.slug])}"
            f"?phone_type={repair_request.phone_type}&phone_model={repair_request.phone_model_id}"
            f"&repair_reference={repair_request.reference}"
        )
    except (ValidationError, RepairPaymentError, PaystackError):
        if payment is not None:
            mark_initialization_failed(payment.pk)
        messages.error(request, "We could not start payment. Your repair request is safe; please try again.")
    except ImproperlyConfigured:
        logger.exception("Paystack configuration is invalid for a repair payment.")
        if payment is not None:
            mark_initialization_failed(payment.pk)
        messages.error(request, "Online payment is temporarily unavailable. Please contact CampusFriend.")
    return redirect("repairs:repair_detail", reference=reference)


@never_cache
@require_safe
def paystack_callback(request):
    reference = (request.GET.get("reference") or request.GET.get("trxref") or "").strip()
    trxref = request.GET.get("trxref")
    if not reference or (trxref and request.GET.get("reference") and trxref != reference):
        return HttpResponse("Invalid payment reference.", status=400)

    payment = get_object_or_404(
        RepairPayment.objects.select_related("repair_request"),
        reference=reference,
    )
    repair_request = payment.repair_request
    guest_session_id = request.session.get(SESSION_GUEST_KEY)
    if not guest_session_id or repair_request.guest_session_id != guest_session_id:
        raise Http404("Payment not found")

    try:
        result = verify_transaction(payment.reference)
        matched = record_verified_transaction(payment.pk, result)
    except PaystackError:
        messages.error(request, "We could not verify your payment yet. No payment status has been changed.")
        return redirect("repairs:repair_detail", reference=repair_request.reference)
    except ImproperlyConfigured:
        logger.exception("Paystack configuration is invalid during repair callback verification.")
        messages.error(request, "We could not verify your payment yet. No payment status has been changed.")
        return redirect("repairs:repair_detail", reference=repair_request.reference)

    if not matched:
        logger.warning("Paystack verification did not match repair payment %s.", payment.reference)
        messages.error(request, "The verified payment details did not match. No payment was marked as paid.")
    else:
        payment.refresh_from_db()
        if payment.status == RepairPayment.Status.PAID:
            messages.success(request, "Payment received. Repair progress will be updated separately.")
        elif payment.status in {RepairPayment.Status.FAILED, RepairPayment.Status.ABANDONED}:
            messages.error(request, "Payment was not completed. You can try again from this repair.")
        else:
            messages.info(request, "Payment is still being confirmed. Refresh this repair shortly.")
    return redirect("repairs:repair_detail", reference=repair_request.reference)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    try:
        validate_paystack_configuration()
    except PaystackError:
        return HttpResponse(status=503)
    except ImproperlyConfigured:
        logger.exception("Paystack repair webhook received with invalid configuration.")
        return HttpResponse(status=503)

    raw_payload = request.body
    received_signature = request.headers.get("X-Paystack-Signature", "")
    expected_signature = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode("utf-8"),
        raw_payload,
        hashlib.sha512,
    ).hexdigest()
    if not received_signature or not hmac.compare_digest(received_signature, expected_signature):
        logger.warning("Rejected repair Paystack webhook with an invalid signature.")
        return HttpResponse(status=401)

    try:
        event = json.loads(raw_payload)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(event, dict):
        return HttpResponse(status=400)
    if event.get("event") != "charge.success":
        return HttpResponse(status=200)
    data = event.get("data")
    if not isinstance(data, dict):
        return HttpResponse(status=400)
    if data.get("status") != "success" or not data.get("reference"):
        return HttpResponse(status=400)

    try:
        payment = RepairPayment.objects.get(reference=data["reference"])
    except RepairPayment.DoesNotExist:
        logger.warning("Rejected repair Paystack webhook with unknown reference %s.", data.get("reference"))
        return HttpResponse(status=404)

    if (
        type(data.get("amount")) is not int
        or data["amount"] != amount_in_subunits(payment.amount)
        or data.get("currency") != payment.currency
    ):
        logger.warning("Rejected repair Paystack webhook with mismatched payment details.")
        return HttpResponse(status=400)
    if not record_verified_transaction(payment.pk, data):
        return HttpResponse(status=400)
    return HttpResponse(status=200)
