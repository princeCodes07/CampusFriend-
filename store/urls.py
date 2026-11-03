from django.urls import path

from . import views


app_name = "store"


urlpatterns = [

    path(
        "shop/",
        views.product_list,
        name="product_list",
    ),

    # Compatibility for previous department URLs.
    path(
        "shop/department/<slug:slug>/",
        views.legacy_department_redirect,
        name="department",
    ),

    path(
        "shop/category/<slug:slug>/",
        views.category_detail,
        name="category",
    ),

    path(
        "shop/product/<slug:slug>/",
        views.product_detail,
        name="product_detail",
    ),

    path(
        "books/",
        views.books,
        name="books",
    ),
]