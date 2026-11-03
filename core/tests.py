from datetime import timedelta
import re

from django.test import TestCase
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from store.models import Category, Product


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class HomepageTests(TestCase):
    def test_homepage_works_with_an_empty_database(self):
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Campus essentials,")
        self.assertContains(response, "Collections will appear here when products are available to browse.")
        self.assertContains(response, "Our featured selection is on its way.")
        self.assertNotContains(response, 'id="latest-title"')
        self.assertNotContains(response, 'id="books-title"')
        for placeholder in ("[BUSINESS_PHONE]", "[WHATSAPP_NUMBER]", "[BUSINESS_EMAIL]"):
            self.assertNotContains(response, placeholder)

    def test_homepage_uses_active_categories_and_at_most_four_visible_featured_products(self):
        category = Category.objects.create(name="Accessories")
        hidden_category = Category.objects.create(name="Hidden category", is_active=False)
        for i in range(10):
            Product.objects.create(category=category, name=f"Featured {i:02}", sku=f"HOME-{i}", price="10.00", stock=3, is_featured=True)
        Product.objects.create(category=category, name="Unavailable", sku="OFF", price="10.00", stock=3, is_featured=True, is_available=False)
        Product.objects.create(category=hidden_category, name="Hidden product", sku="HIDDEN", price="10.00", stock=3, is_featured=True)
        Product.objects.create(category=category, name="Not featured", sku="PLAIN", price="10.00")
        with self.assertNumQueries(7):
            response = self.client.get(reverse("core:home"))
        self.assertEqual(len(response.context["featured_products"]), 4)
        self.assertEqual(list(response.context["categories"]), [category])
        for name in ("Unavailable", "Hidden product", "Hidden category"):
            self.assertNotContains(response, name)
        self.assertContains(response, "Not featured")
        self.assertNotContains(
            response,
            f'href="{reverse("store:category", args=[category.slug])}"',
        )

    def test_featured_selection_excludes_sold_out_items_and_updates_when_stock_runs_out(self):
        category = Category.objects.create(name="Accessories")
        for name, stock in (("A sold out", 0), ("B unconfirmed", None)):
            Product.objects.create(category=category, name=name, sku=name, price="10.00", stock=stock, is_featured=True)
        stocked = [Product.objects.create(category=category, name=f"Featured {i}", sku=f"STOCKED-{i}",
                                          price="10.00", stock=1, is_featured=True) for i in range(5)]
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["featured_products"], stocked[:4])
        # Stock changes can come directly from inventory/payment updates.
        Product.objects.filter(pk=stocked[0].pk).update(stock=0)
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["featured_products"], stocked[1:])

    def test_homepage_categories_share_one_toolbar_without_parent_headings(self):
        parent = Category.objects.create(name="Accessories")
        child = Category.objects.create(name="Phone Accessories", parent=parent)
        audio = Category.objects.create(name="Audio", parent=parent, sort_order=1)
        books_section = Category.objects.create(name="Books & Study", sort_order=1)
        books = Category.objects.create(name="Books", parent=books_section)
        Product.objects.create(
            category=child,
            name="Phone case",
            sku="PHONE-CASE",
            price="10.00",
        )
        for category in (audio, books):
            Product.objects.create(category=category, name=f"{category.name} item", sku=f"CATEGORY-{category.pk}", price="20.00")

        response = self.client.get(reverse("core:home"))

        self.assertNotContains(
            response,
            f'<h3 id="category-group-1">{parent.name}</h3>',
            html=True,
        )
        self.assertContains(
            response,
            f'href="{reverse("store:category", args=[child.slug])}"',
        )
        self.assertNotContains(
            response,
            f'href="{reverse("store:category", args=[parent.slug])}"',
        )
        self.assertNotContains(response, "EXPLORE THE STORE")
        navigation = response.content.decode().split('aria-label="Store categories">', 1)[1].split("</nav>", 1)[0]
        self.assertEqual(
            re.findall(r'href="([^"]+)"', navigation),
            [reverse("store:category", args=[category.slug]) for category in (child, audio, books)],
        )
        self.assertContains(response, f'<form class="catalog-controls" method="get" action="{reverse("store:product_list")}"')
        self.assertEqual([value for value, label in response.context["sort_options"]], ["name", "price_low", "price_high", "newest"])

    def test_navigation_has_all_required_destinations(self):
        response = self.client.get(reverse("core:home"))
        for name in ("core:home", "store:product_list", "store:books", "repairs:home", "orders:order_list"):
            self.assertContains(response, f'href="{reverse(name)}"')
        self.assertContains(response, 'aria-label="Cart, 0 items"')
        self.assertContains(response, f'href="{reverse("orders:cart_detail")}"')
        self.assertContains(response, "Skip to content")
        navigation = response.content.decode().split('id="primary-navigation"')[1].split("</nav>")[0]
        self.assertEqual(
            re.findall(r">([^<]+)</a>", navigation),
            ["Home", "Store", "Repairs", "Books", "Track Order"],
        )
        self.assertContains(response, "Sign in")
        self.assertContains(response, "Sign up")
        for name in ("accounts:login", "accounts:signup"):
            self.assertContains(response, f'href="{reverse(name)}?next=/"')
        self.assertNotIn("/shop/department/", navigation)

    def test_category_links_require_visible_products_but_not_positive_stock(self):
        empty = Category.objects.create(name="Empty category")
        hidden_only = Category.objects.create(name="Hidden only")
        inactive = Category.objects.create(name="Inactive", is_active=False)
        sold_out = Category.objects.create(name="Sold out collection")
        unconfirmed = Category.objects.create(name="Unconfirmed collection")
        for category, stock, available in ((hidden_only, 4, False), (inactive, 4, True),
                                           (sold_out, 0, True), (unconfirmed, None, True)):
            Product.objects.create(category=category, name=f"Item {category.pk}", sku=f"CAT-{category.pk}",
                                   price="10.00", stock=stock, is_available=available)
        for url in (reverse("core:home"), reverse("store:product_list")):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(set(response.context["categories"]), {sold_out, unconfirmed})
                for category in (empty, hidden_only, inactive):
                    self.assertNotContains(response, f'href="{reverse("store:category", args=[category.slug])}"')

    def test_latest_products_use_creation_date_and_are_limited_to_four(self):
        category = Category.objects.create(name="Accessories")
        products = []
        created = timezone.now() - timedelta(days=10)
        for index in range(10):
            product = Product.objects.create(category=category, name=f"Item {index}", sku=f"LATEST-{index}", price="10.00")
            Product.objects.filter(pk=product.pk).update(created_at=created + timedelta(days=index))
            products.append(product)
        Product.objects.filter(pk=products[0].pk).update(updated_at=timezone.now())
        response = self.client.get(reverse("core:home"))
        self.assertEqual(
            list(response.context["latest_products"]),
            products[-1:-5:-1],
        )
        self.assertContains(response, f'href="{reverse("store:product_list")}?sort=newest"')

    def test_homepage_books_share_catalog_visibility_and_are_limited_to_four(self):
        books = Category.objects.create(name="Books")
        study = Category.objects.create(name="Study Materials")
        for index in range(6):
            Product.objects.create(category=books if index < 5 else study, name=f"Book {index}",
                                   sku=f"BOOK-{index}", price="20.00", stock=2)
        Product.objects.create(category=books, name="Unpublished book", sku="PRIVATE-BOOK", price="20.00", is_available=False)
        response = self.client.get(reverse("core:home"))
        expected = list(Product.objects.filter(is_available=True).order_by("-created_at", "-pk")[:4])
        self.assertEqual(list(response.context["book_products"]), expected)
        self.assertContains(response, 'id="books-title"')
        self.assertNotContains(response, "Unpublished book")
        books.is_active = False
        books.save()
        response = self.client.get(reverse("core:home"))
        self.assertEqual(list(response.context["book_products"]), [Product.objects.get(sku="BOOK-5")])

    @override_settings(BOOKS_CATEGORY_SLUG="reading")
    def test_homepage_and_books_page_share_configured_category_and_name_fallback(self):
        fallback = Category.objects.create(name="Books", slug="books")
        configured = Category.objects.create(name="Reading", slug="reading")
        first = Product.objects.create(category=fallback, name="Fallback book", sku="FALLBACK", price="10.00")
        second = Product.objects.create(category=configured, name="Configured book", sku="CONFIGURED", price="10.00")
        for expected in (second, first):
            home = self.client.get(reverse("core:home"))
            listing = self.client.get(reverse("store:books"))
            self.assertEqual(list(home.context["book_products"]), [expected])
            self.assertEqual(list(listing.context["page_obj"]), [expected])
            self.assertEqual(self.client.get(expected.get_absolute_url()).context["nav_section"], "books")
            configured.is_active = False
            configured.save()

    def test_repairs_promotion_links_to_available_request_and_tracking_workflow(self):
        response = self.client.get(reverse("core:home"))
        for text in ("Phone repairs", "Laptop issues", "All Electronic issues", "Software problems",
                     "Submit a repair request online and check its status from your repair page."):
            self.assertContains(response, text)
        self.assertNotContains(response, "Coming soon")
        self.assertNotContains(response, "Online repair booking is coming soon.")
        self.assertContains(response, f'href="{reverse("repairs:home")}"', count=4)
        self.assertNotContains(response, "Secure payments")
        self.assertNotContains(response, "Book a Repair")
        self.assertNotContains(response, "Track Repair")

    def test_repairs_links_open_the_repairs_app_and_mark_navigation_active(self):
        response = self.client.get(reverse("repairs:home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Phone Repairs")
        self.assertContains(response, "Laptop Repairs")
        self.assertContains(response, "Accessories & Electronics Repair")
        self.assertContains(response, '<form class="header-search"', count=1)
        self.assertNotContains(response, "Paystack")
        self.assertNotContains(response, "deposit")
        self.assertTemplateUsed(response, "repairs/landing.html")
        self.assertContains(response, '<a href="/repairs/" aria-current="page">Repairs</a>', html=True)

    @override_settings(DEBUG=False)
    def test_missing_page_uses_the_site_error_page(self):
        response = self.client.get("/missing-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "Let's get you back to campus.", status_code=404)

    @override_settings(BUSINESS_PHONE="Test phone", WHATSAPP_NUMBER="Test WhatsApp", BUSINESS_EMAIL="test@example.com")
    def test_footer_displays_owner_supplied_business_details(self):
        response = self.client.get(reverse("core:home"))
        for detail in ("Test phone", "Test WhatsApp", "test@example.com"):
            self.assertContains(response, detail)
