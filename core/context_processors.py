from django.conf import settings

from .models import BusinessContact


def business_contact(request):
    contact = BusinessContact.objects.first()

    return {
        "business_contact": {
            # Existing contact information from settings.py
            "phone": settings.BUSINESS_PHONE,
            "whatsapp": settings.WHATSAPP_NUMBER,
            "email": settings.BUSINESS_EMAIL,

            # Social links managed through Django Admin
            "instagram_url": contact.instagram_url if contact else "",
            "tiktok_url": contact.tiktok_url if contact else "",
            "snapchat_url": contact.snapchat_url if contact else "",
            "whatsapp_chat_url": contact.whatsapp_chat_url if contact else "",
            "whatsapp_channel_url": contact.whatsapp_channel_url if contact else "",
        }
    }
