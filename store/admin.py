from django.contrib import admin

from .models import Category, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "sku",
        "category",
        "price",
        "stock",
        "is_available",
        "is_featured",
    )
    list_filter = ("category", "is_available", "is_featured")
    search_fields = ("name", "sku", "short_description", "description", "category__name")
    list_select_related = ("category",)
    autocomplete_fields = ("category",)
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("name", "category", "sku", "slug")}),
        ("Description and image", {"fields": ("short_description", "description", "image")}),
        ("Pricing and stock", {"fields": ("price", "old_price", "stock")}),
        ("Visibility", {"fields": ("is_available", "is_featured")}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )
