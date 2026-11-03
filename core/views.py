from django.shortcuts import render
from django.views.decorators.http import require_safe

from store.catalog import (
    SORT_OPTIONS,
    books_category,
    category_groups,
    populated_categories,
    visible_book_products,
    visible_products,
)


@require_safe
def home(request):
    featured_products = list(
        visible_products().filter(is_featured=True, stock__gt=0)[:4]
    )
    featured_ids = [product.pk for product in featured_products]
    latest_products = (
        visible_products()
        .exclude(pk__in=featured_ids)
        .order_by("-created_at", "-pk")[:4]
    )
    return render(
        request,
        "core/home.html",
        {
            "sort_options": [(value, option[0]) for value, option in SORT_OPTIONS.items()],
            "categories": populated_categories(homepage_only=True),
            "category_groups": category_groups(homepage_only=True),
            "featured_products": featured_products,
            "latest_products": latest_products,
            "book_products": visible_book_products(books_category())
            .order_by("-created_at", "-pk")[:4],
            "nav_section": "home",
        },
    )
