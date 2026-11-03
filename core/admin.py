from django.contrib import admin

from .models import BusinessContact

@admin.register(BusinessContact)
class BusinessContactAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Business contact",
            {
                "fields": (
                    "phone",
                    "whatsapp",
                    "email",
                )
            },
        ),
        (
            "Social media links",
            {
                "fields": (
                    "instagram_url",
                    "tiktok_url",
                    "snapchat_url",
                    "whatsapp_chat_url",
                    "whatsapp_channel_url",
                )
            },
        ),
    )
