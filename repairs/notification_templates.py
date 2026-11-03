def repair_request_received(repair):
    return {
        "subject": f"Repair request {repair.reference} received",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"We received your repair request {repair.reference}.\n\n"
            "Our team will review it and contact you using the details you provided.\n\n"
            "CampusFriend Repairs"
        ),
    }


def price_confirmed(repair):
    return {
        "subject": f"Repair price confirmed — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"The price for your repair {repair.reference} has been confirmed.\n\n"
            "You can review the repair details using your repair page.\n\n"
            "CampusFriend Repairs"
        ),
    }


def payment_received(repair):
    return {
        "subject": f"Payment received — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"Your payment for repair {repair.reference} has been received successfully.\n\n"
            "Your repair will now proceed through the repair process.\n\n"
            "CampusFriend Repairs"
        ),
    }


def repair_in_progress(repair):
    return {
        "subject": f"Repair in progress — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"Work on your repair {repair.reference} is now in progress.\n\n"
            "CampusFriend Repairs"
        ),
    }


def repair_ready(repair):
    return {
        "subject": f"Your repair is ready — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"Your repair {repair.reference} is ready.\n\n"
            "Please follow the arrangement provided by our team.\n\n"
            "CampusFriend Repairs"
        ),
    }


def repair_completed(repair):
    return {
        "subject": f"Repair completed — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"Your repair {repair.reference} has been completed.\n\n"
            "Thank you for using CampusFriend Repairs."
        ),
    }


def repair_cancelled(repair):
    return {
        "subject": f"Repair update — {repair.reference}",
        "message": (
            f"Hello {repair.customer_name or 'there'},\n\n"
            f"Your repair request {repair.reference} has been cancelled.\n\n"
            "Please contact CampusFriend if you have questions.\n\n"
            "CampusFriend Repairs"
        ),
    }