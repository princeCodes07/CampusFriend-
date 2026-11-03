from django.db import models

class BusinessContact(models.Model):
    phone = models.CharField(
        max_length=30,
        blank=True,
    )

    whatsapp = models.CharField(
        max_length=30,
        blank=True,
    )

    email = models.EmailField(
        blank=True,
    )

    instagram_url = models.URLField(
        "Instagram profile URL",
        max_length=500,
        blank=True,
    )

    tiktok_url = models.URLField(
        "TikTok profile URL",
        max_length=500,
        blank=True,
    )

    snapchat_url = models.URLField(
        "Snapchat profile URL",
        max_length=500,
        blank=True,
    )

    whatsapp_chat_url = models.URLField(
        "WhatsApp chat URL",
        max_length=500,
        blank=True,
    )

    whatsapp_channel_url = models.URLField(
        "WhatsApp Channel URL",
        max_length=500,
        blank=True,
    )

    def __str__(self):
        return "CampusFriend Business Contact"
