from django.contrib import admin, messages
from django.db.models import Count, Q
from django.utils.html import format_html

from .models import Category, Product


class StockStatusFilter(admin.SimpleListFilter):
    """
    Product stock filter used in Django Admin.

    stock=None  -> stock not confirmed
    stock=0     -> confirmed out of stock
    stock>0     -> confirmed in stock
    """

    title = "stock status"
    parameter_name = "stock_status"

    def lookups(self, request, model_admin):
        return (
            ("in_stock", "In stock"),
            ("out_of_stock", "Out of stock"),
            ("unconfirmed", "Stock not confirmed"),
        )

    def queryset(self, request, queryset):
        value = self.value()

        if value == "in_stock":
            return queryset.filter(stock__gt=0)

        if value == "out_of_stock":
            return queryset.filter(stock=0)

        if value == "unconfirmed":
            return queryset.filter(stock__isnull=True)

        return queryset


# ============================================================
# CATEGORY ADMIN
# ============================================================


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    Manage CampusFriend's database-driven Store taxonomy.

    Example:

    Accessories
        ├── Audio
        ├── Power Banks
        └── Phone Accessories
    """

    list_display = (
        "name",
        "parent",
        "sort_order",
        "public_product_count",
        "show_on_homepage",
        "is_active",
    )

    list_display_links = (
        "name",
    )

    list_editable = (
        "sort_order",
        "show_on_homepage",
        "is_active",
    )

    list_filter = (
        "is_active",
        "show_on_homepage",
        (
            "parent",
            admin.RelatedOnlyFieldListFilter,
        ),
    )

    search_fields = (
        "name",
        "slug",
        "description",
        "parent__name",
    )

    ordering = (
        "sort_order",
        "name",
    )

    list_select_related = (
        "parent",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )

    prepopulated_fields = {
        "slug": (
            "name",
        )
    }

    list_per_page = 50

    save_on_top = True

    fieldsets = (
        (
            "Category",
            {
                "fields": (
                    "name",
                    "slug",
                    "parent",
                ),
                "description": (
                    "Top-level categories act as Store sections. "
                    "Specific categories such as Audio, Power Banks "
                    "and Phone Accessories should sit underneath them."
                ),
            },
        ),
        (
            "Store presentation",
            {
                "fields": (
                    "description",
                    "sort_order",
                    "show_on_homepage",
                    "is_active",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs,
    ):
        """
        CampusFriend currently uses a two-level taxonomy:

        Store section
            -> Product category

        Therefore the parent selector should only contain
        top-level Store sections.
        """

        if db_field.name == "parent":
            kwargs["queryset"] = (
                Category.objects
                .filter(parent__isnull=True)
                .order_by(
                    "sort_order",
                    "name",
                )
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )

    def get_queryset(self, request):
        """
        Annotate product counts once rather than issuing
        extra queries for every row in the Admin list.
        """

        return (
            super()
            .get_queryset(request)
            .select_related("parent")
            .annotate(
                _direct_public_count=Count(
                    "products",
                    filter=Q(
                        products__is_available=True,
                    ),
                    distinct=True,
                ),
                _child_public_count=Count(
                    "children__products",
                    filter=Q(
                        children__is_active=True,
                        children__products__is_available=True,
                    ),
                    distinct=True,
                ),
            )
        )

    @admin.display(
        description="Public products",
    )
    def public_product_count(self, obj):

        if not obj.is_active:
            return 0

        if (
            obj.parent_id
            and not obj.parent.is_active
        ):
            return 0

        return (
            obj._direct_public_count
            + obj._child_public_count
        )
@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):

    list_display = (
        "product_thumbnail",
        "name",
        "sku",
        "category",
        "price",
        "stock",
        "is_available",
        "is_featured",
    )

    # Without this, Django could make the thumbnail
    # the clickable edit link because it is first.
    list_display_links = (
        "name",
    )

    list_editable = (
        "stock",
        "is_available",
        "is_featured",
    )

    list_filter = (
        (
            "category",
            admin.RelatedOnlyFieldListFilter,
        ),
        StockStatusFilter,
        "is_available",
        "is_featured",
    )

    search_fields = (
        "name",
        "sku",
        "short_description",
        "description",
        "category__name",
        "category__parent__name",
    )

    list_select_related = (
        "category",
        "category__parent",
    )

    ordering = (
        "name",
        "pk",
    )

    readonly_fields = (
        "image_preview",
        "storefront_link",
        "created_at",
        "updated_at",
    )

    actions = (
        "publish_products",
        "hide_products",
        "feature_products",
        "unfeature_products",
    )

    list_per_page = 50

    save_on_top = True

    prepopulated_fields = {
        "slug": (
            "name",
        )
    }

    fieldsets = (
        (
            "Product",
            {
                "fields": (
                    "name",
                    "category",
                    "sku",
                    "slug",
                ),
                "description": (
                    "Assign products to the most specific category. "
                    "For example, a power bank should use "
                    "'Accessories → Power Banks', not 'Accessories'."
                ),
            },
        ),
        (
            "Description and image",
            {
                "fields": (
                    "short_description",
                    "description",
                    "image",
                    "image_preview",
                )
            },
        ),
        (
            "Pricing and stock",
            {
                "fields": (
                    "price",
                    "old_price",
                    "stock",
                ),
                "description": (
                    "Leave Old price blank unless the product is "
                    "genuinely discounted. Blank stock means stock "
                    "has not yet been confirmed; zero means the "
                    "product is confirmed out of stock."
                ),
            },
        ),
        (
            "Store visibility",
            {
                "fields": (
                    "is_available",
                    "is_featured",
                    "storefront_link",
                ),
                "description": (
                    "Available products in active categories appear "
                    "in the Store. Featured products may also appear "
                    "on the homepage."
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )

    def formfield_for_foreignkey(
        self,
        db_field,
        request,
        **kwargs,
    ):
        """
        Prefer leaf categories for products.

        This prevents inventory from continuing to be placed
        directly inside broad Store sections such as Accessories.
        """

        if db_field.name == "category":
            kwargs["queryset"] = (
                Category.objects
                .filter(
                    children__isnull=True,
                )
                .select_related("parent")
                .order_by(
                    "parent__sort_order",
                    "parent__name",
                    "sort_order",
                    "name",
                )
                .distinct()
            )

        return super().formfield_for_foreignkey(
            db_field,
            request,
            **kwargs,
        )

    # --------------------------------------------------------
    # Product list image
    # --------------------------------------------------------

    @admin.display(
        description="Image",
    )
    def product_thumbnail(self, obj):
        if not obj.image:
            return "—"

        return format_html(
            (
                '<img src="{}" '
                'alt="{}" '
                'width="48" '
                'height="48" '
                'loading="lazy" '
                'style="'
                'width:48px;'
                'height:48px;'
                'object-fit:contain;'
                'border-radius:6px;'
                'background:#fff;'
                '">'
            ),
            obj.image.url,
            obj.name,
        )

    # --------------------------------------------------------
    # Bulk actions
    # --------------------------------------------------------

    @admin.action(
        description="Publish selected products",
    )
    def publish_products(
        self,
        request,
        queryset,
    ):
        queryset.update(
            is_available=True,
        )

    @admin.action(
        description="Hide selected products",
    )
    def hide_products(
        self,
        request,
        queryset,
    ):
        queryset.update(
            is_available=False,
        )

    @admin.action(
        description="Feature selected products",
    )
    def feature_products(
        self,
        request,
        queryset,
    ):
        skipped = queryset.filter(Q(stock=0) | Q(stock__isnull=True)).count()
        updated = queryset.filter(stock__gt=0).update(
            is_featured=True,
        )
        self.message_user(request, f"Featured {updated} product(s) with confirmed stock.")
        if skipped:
            self.message_user(
                request,
                f"Skipped {skipped} product(s) with zero or unconfirmed stock.",
                level=messages.WARNING,
            )

    @admin.action(
        description=(
            "Remove selected products from featured"
        ),
    )
    def unfeature_products(
        self,
        request,
        queryset,
    ):
        queryset.update(
            is_featured=False,
        )

    # --------------------------------------------------------
    # Product editing helpers
    # --------------------------------------------------------

    @admin.display(
        description="Photo preview",
    )
    def image_preview(
        self,
        obj,
    ):
        if not obj or not obj.image:
            return (
                "Upload a product photo using "
                "the Image field above."
            )

        return format_html(
            (
                '<img src="{}" '
                'alt="{}" '
                'width="180" '
                'loading="lazy" '
                'style="'
                'max-width:180px;'
                'max-height:180px;'
                'object-fit:contain;'
                'border-radius:8px;'
                'background:#fff;'
                '">'
            ),
            obj.image.url,
            obj.name,
        )

    @admin.display(
        description="Storefront",
    )
    def storefront_link(
        self,
        obj,
    ):
        if not obj or not obj.pk:
            return (
                "Save this product to get "
                "its storefront link."
            )

        if not obj.is_available:
            return (
                "Hidden from customers because "
                "this product is not marked available."
            )

        if not obj.category.is_active:
            return (
                "Hidden from customers because "
                "its category is inactive."
            )

        if (
            obj.category.parent_id
            and not obj.category.parent.is_active
        ):
            return (
                "Hidden from customers because "
                "its parent Store section is inactive."
            )

        return format_html(
            '<a href="{}" target="_blank" rel="noopener">'
            "Open product page ↗"
            "</a>",
            obj.get_absolute_url(),
        )