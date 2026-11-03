import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from . import notification_templates
from .models import RepairNotification, RepairRequest


logger = logging.getLogger(__name__)

STATUS_NOTIFICATION_EVENTS = {
    RepairRequest.Status.REQUESTED: ("repair_request_received", notification_templates.repair_request_received),
    RepairRequest.Status.PRICE_CONFIRMED: ("price_confirmed", notification_templates.price_confirmed),
    RepairRequest.Status.PAID: ("payment_received", notification_templates.payment_received),
    RepairRequest.Status.REPAIR_IN_PROGRESS: ("repair_in_progress", notification_templates.repair_in_progress),
    RepairRequest.Status.READY: ("repair_ready", notification_templates.repair_ready),
    RepairRequest.Status.COMPLETED: ("repair_completed", notification_templates.repair_completed),
    RepairRequest.Status.CANCELLED: ("repair_cancelled", notification_templates.repair_cancelled),
}


def _create_and_dispatch(*, repair_id, event, subject, message):
    try:
        repair = RepairRequest.objects.get(pk=repair_id)
        recipient = repair.email.strip()
        if not recipient:
            return None
        notification, created = RepairNotification.objects.get_or_create(
            repair=repair,
            channel=RepairNotification.Channel.EMAIL,
            event=event,
            defaults={
                "recipient": recipient,
                "subject": subject,
                "message": message,
            },
        )
        if created:
            send_notification(notification.pk)
        return notification
    except Exception:
        logger.exception("Could not create or dispatch repair notification for repair id %s.", repair_id)
        return None


def create_email_notification(repair, *, event, subject, message):
    recipient = (repair.email or "").strip()
    if not recipient:
        return None

    result = {"notification": None}
    transaction.on_commit(
        lambda: result.update(notification=_create_and_dispatch(
            repair_id=repair.pk,
            event=event,
            subject=subject,
            message=message,
        )),
        robust=True,
    )
    return result["notification"]


def create_notification_for_status(repair):
    event_builder = STATUS_NOTIFICATION_EVENTS.get(repair.status)
    if event_builder is None or not (repair.email or "").strip():
        return None
    event, builder = event_builder
    content = builder(repair)
    return create_email_notification(
        repair,
        event=event,
        subject=content["subject"],
        message=content["message"],
    )


def _email_delivery_error():
    smtp_backend = "django.core.mail.backends.smtp.EmailBackend"
    if (
        settings.EMAIL_BACKEND != smtp_backend
        or not settings.EMAIL_HOST.strip()
        or not settings.DEFAULT_FROM_EMAIL.strip()
    ):
        return "Email delivery is not configured."
    return ""


def send_notification(notification_or_id):
    notification_id = notification_or_id.pk if isinstance(notification_or_id, RepairNotification) else notification_or_id
    notification = RepairNotification.objects.get(pk=notification_id)
    if notification.status == RepairNotification.Status.SENT:
        return True
    if notification.status != RepairNotification.Status.PENDING:
        return False

    try:
        configuration_error = _email_delivery_error()
        if configuration_error:
            raise RuntimeError(configuration_error)
        if notification.channel != RepairNotification.Channel.EMAIL:
            raise RuntimeError(f"Delivery for {notification.get_channel_display()} is not configured.")
        try:
            validate_email(notification.recipient)
        except ValidationError as error:
            raise RuntimeError("The notification recipient email address is invalid.") from error

        sent_count = send_mail(
            subject=notification.subject,
            message=notification.message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[notification.recipient],
            fail_silently=False,
        )
        if sent_count != 1:
            raise RuntimeError("The email provider did not accept the notification.")
    except Exception as error:
        notification.status = RepairNotification.Status.FAILED
        notification.error_message = str(error)[:4000]
        notification.sent_at = None
        notification.save(update_fields={"status", "error_message", "sent_at"})
        logger.warning(
            "Repair notification %s failed to send: %s",
            notification.pk,
            notification.error_message,
        )
        return False

    notification.status = RepairNotification.Status.SENT
    notification.sent_at = timezone.now()
    notification.error_message = ""
    notification.save(update_fields={"status", "sent_at", "error_message"})
    return True


def retry_notification(notification):
    notification_id = notification.pk if isinstance(notification, RepairNotification) else notification
    claimed = RepairNotification.objects.filter(
        pk=notification_id,
        status=RepairNotification.Status.FAILED,
    ).update(
        status=RepairNotification.Status.PENDING,
        error_message="",
    )
    if not claimed:
        return False
    return send_notification(notification_id)