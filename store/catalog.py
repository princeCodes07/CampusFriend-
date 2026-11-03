"""Shared database-driven catalog discovery and visibility rules."""

from django.conf import settings
from django.db.models import Q

from .models import Category, Product


SORT_OPTIONS = {
    "name": ("Name: A to Z", ("name", "pk")),
    "price_low": ("Price: low to high", ("price", "name", "pk")),
    "price_high": ("Price: high to low", ("-price", "name", "pk")),
    "newest": ("Newest arrivals", ("-created_at", "-pk")),
}


def navigation_section(category):
    """
    Determine which main navigation item should be active.
    """

    if (
        category.slug
        in (
            settings.BOOKS_CATEGORY_SLUG,
            "study-materials",
        )
        or category.name.lower() == "books"
    ):
        return "books"

    if (
        category.parent_id
        and category.parent.slug == "books-study"
    ):
        return "books"

    return "shop"


def visible_products():
    """
    Single source of truth for products customers
    are allowed to browse.
    """

    return (
        Product.objects
        .filter(
            Q(category__parent__isnull=True)
            | Q(category__parent__is_active=True),
            is_available=True,
            category__is_active=True,
        )
        .select_related(
            "category",
            "category__parent",
        )
    )


def populated_categories(*, homepage_only=False):
    """
    Return active categories that actually contain
    customer-visible products.

    Empty categories remain available in Admin but
    are not unnecessarily presented to customers.
    """

    queryset = (
        Category.objects
        .filter(
            is_active=True,
            pk__in=visible_products()
            .values("category_id"),
        )
        .select_related("parent")
    )

    if homepage_only:
        queryset = queryset.filter(
            show_on_homepage=True
        )

    return queryset.order_by(
        "parent__sort_order",
        "parent__name",
        "sort_order",
        "name",
        "pk",
    )


def category_groups(*, homepage_only=False):
    """
    Group populated categories by their Store section.
    """

    groups = []
    positions = {}

    for category in populated_categories(
        homepage_only=homepage_only
    ):

        group = (
            category.parent
            if category.parent
            and category.parent.is_active
            else None
        )

        key = (
            group.pk
            if group
            else f"standalone:{category.pk}"
        )

        if key not in positions:

            positions[key] = len(groups)

            groups.append(
                {
                    "section": group,
                    "categories": [],
                }
            )

        groups[
            positions[key]
        ]["categories"].append(
            category
        )

    section_ids = {
        group["section"].pk
        for group in groups
        if group["section"] is not None
    }

    for group in groups:
        group["is_duplicate_parent"] = (
            group["section"] is None
            and len(group["categories"]) == 1
            and group["categories"][0].pk in section_ids
        )

    return groups


def products_for_category(category):
    """
    Return visible products belonging to this
    category or its immediate active children.

    This allows:

    Accessories
        Audio
        Power Banks
        Phone Accessories

    and visiting Accessories shows products
    from those children.
    """

    child_ids = (
        category.children
        .filter(is_active=True)
        .values("pk")
    )

    return visible_products().filter(
        Q(category=category)
        | Q(category_id__in=child_ids)
    )


def books_category():

    active = (
        Category.objects
        .filter(is_active=True)
        .filter(
            Q(parent__isnull=True)
            | Q(parent__is_active=True)
        )
        .select_related("parent")
    )

    category = active.filter(
        slug=settings.BOOKS_CATEGORY_SLUG
    ).first()

    if category is None:

        category = active.filter(
            name__iexact="Books"
        ).first()

    return category


def visible_book_products(category=None):
    """
    Books remain ordinary Products while
    supporting the Study Materials category too.
    """

    books_filter = (
        Q(category=category)
        if category is not None
        else Q(pk__in=[])
    )

    return visible_products().filter(
        books_filter
        | Q(category__slug="study-materials")
    )
