from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_safe

from .catalog import (
    SORT_OPTIONS,
    books_category,
    category_groups,
    navigation_section,
    populated_categories,
    products_for_category,
    visible_book_products,
    visible_products,
)
from .models import Category


def _catalog_response(request, *, category=None, is_books=False):
    if is_books:
        products = visible_book_products(category)
    elif category is not None:
        products = products_for_category(category)
    else:
        products = visible_products()

    query = request.GET.get("q", "").strip()[:200]
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(short_description__icontains=query)
            | Q(description__icontains=query)
            | Q(sku__icontains=query)
            | Q(category__name__icontains=query)
        )

    in_stock = request.GET.get("in_stock") == "1"
    if in_stock:
        products = products.filter(stock__gt=0)

    sort = request.GET.get("sort", "name")
    if sort not in SORT_OPTIONS:
        sort = "name"
    products = products.order_by(*SORT_OPTIONS[sort][1])

    paginator = Paginator(products, 12)
    page = paginator.get_page(request.GET.get("page"))
    nav_section = "books" if is_books else "shop"
    if category and not is_books:
        nav_section = navigation_section(category)

    return render(
        request,
        "store/product_list.html",
        {
            "category": category,
            "categories": populated_categories(),
            "category_groups": category_groups(),
            "page_obj": page,
            "query": query,
            "sort": sort,
            "sort_options": [
                (value, option[0]) for value, option in SORT_OPTIONS.items()
            ],
            "in_stock": in_stock,
            "is_books": is_books,
            "nav_section": nav_section,
        },
    )


@require_safe
def product_list(request):
    return _catalog_response(request)


@require_safe
def legacy_department_redirect(request, slug):
    """
    Keep old department URLs working while
    the database Category model replaces them.
    """
    category = get_object_or_404(Category, slug=slug, is_active=True)
    destination = category.get_absolute_url()
    query = request.GET.urlencode()
    if query:
        destination = f"{destination}?{query}"
    return redirect(destination, permanent=True)


@require_safe
def category_detail(request, slug):
    category = get_object_or_404(
        Category.objects.select_related("parent").filter(
            Q(parent__isnull=True) | Q(parent__is_active=True)
        ),
        slug=slug,
        is_active=True,
    )
    return _catalog_response(request, category=category)


@require_safe
def books(request):
    return _catalog_response(request, category=books_category(), is_books=True)


@require_safe
def product_detail(request, slug):
    product = get_object_or_404(visible_products(), slug=slug)
    related_products = (
        visible_products()
        .filter(category=product.category)
        .exclude(pk=product.pk)
        .order_by("-is_featured", "name", "pk")[:4]
    )
    return render(
        request,
        "store/product_detail.html",
        {
            "product": product,
            "nav_section": navigation_section(product.category),
            "related_products": related_products,
        },
    )
