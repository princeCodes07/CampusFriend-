from decimal import Decimal
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Category, Product


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class StorefrontTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.accessories = Category.objects.create(name="Accessories")
        cls.books_category = Category.objects.create(name="Growth Books", slug="books")
        cls.inactive_category = Category.objects.create(name="Hidden collection", is_active=False)
        cls.charger = Product.objects.create(
            category=cls.accessories, name="Type-C Fast Charger", sku="CHARGE-42",
            price=Decimal("85.00"), old_price=Decimal("95.00"), stock=4,
            short_description="Pocket companion", description="Reliable charging for lectures.",
            is_featured=True,
        )
        cls.sold_out = Product.objects.create(
            category=cls.accessories, name="Power Bank", sku="POWER", price="100.00", stock=0,
        )
        cls.book = Product.objects.create(
            category=cls.books_category, name="Good Habits", sku="BOOK", price="75.00", stock=2,
        )
        cls.unavailable = Product.objects.create(
            category=cls.accessories, name="Private Charger", sku="PRIVATE", price="90.00",
            is_available=False, is_featured=True,
        )
        cls.hidden = Product.objects.create(
            category=cls.inactive_category, name="Hidden Charger", sku="HIDDEN", price="90.00",
            is_featured=True,
        )

    def test_shop_shows_only_visible_products_including_sold_out(self):
        response = self.client.get(reverse("store:product_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.context["page_obj"]), {self.charger, self.book, self.sold_out})
        self.assertContains(response, "Out of stock")
        self.assertNotContains(response, self.unavailable.name)
        self.assertNotContains(response, self.inactive_category.name)

    def test_category_shows_description_and_only_its_visible_products(self):
        self.accessories.description = "Keep your everyday devices connected."
        self.accessories.save()
        response = self.client.get(reverse("store:category", args=[self.accessories.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.accessories.description)
        self.assertEqual(set(response.context["page_obj"]), {self.charger, self.sold_out})

    def test_store_category_navigation_flattens_children_and_keeps_standalone_categories(self):
        audio = Category.objects.create(name="Audio", parent=self.accessories)
        Product.objects.create(
            category=audio,
            name="Earbuds",
            sku="AUDIO-NAV",
            price="50.00",
        )

        response = self.client.get(reverse("store:product_list"))
        parent_url = reverse("store:category", args=[self.accessories.slug])
        child_url = reverse("store:category", args=[audio.slug])

        navigation = response.content.decode().split('aria-label="Product categories">', 1)[1].split("</nav>", 1)[0]
        self.assertNotIn(f'href="{parent_url}"', navigation)
        self.assertNotIn('store-category-parent', navigation)
        self.assertEqual(navigation.count(f'href="{child_url}"'), 1)
        books_url = reverse("store:category", args=[self.books_category.slug])
        self.assertEqual(navigation.count(f'href="{books_url}"'), 1)
        self.assertContains(response, 'class="category-all"')

        response = self.client.get(child_url)
        self.assertContains(
            response,
            f'<a class="category-filter" href="{child_url}" aria-current="page">Audio</a>',
            html=True,
        )

    def test_invalid_and_inactive_categories_return_404(self):
        for slug in ("does-not-exist", self.inactive_category.slug):
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get(reverse("store:category", args=[slug])).status_code, 404)

    def test_product_detail_displays_information_and_add_to_cart_form(self):
        response = self.client.get(reverse("store:product_detail", args=[self.charger.slug]))
        self.assertEqual(response.status_code, 200)
        for text in (self.charger.name, self.charger.sku, self.charger.description,
                     "GH₵ 85.00", "GH₵ 95.00", "4 available", "Guest checkout is available"):
            self.assertContains(response, text)
        self.assertContains(response, f'action="{reverse("orders:cart_add", args=[self.charger.pk])}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'max="4" required')
        self.assertNotContains(response, 'type="submit" disabled')

    def test_invalid_unavailable_and_inactive_category_products_return_404(self):
        for slug in ("does-not-exist", self.unavailable.slug, self.hidden.slug):
            with self.subTest(slug=slug):
                self.assertEqual(self.client.get(reverse("store:product_detail", args=[slug])).status_code, 404)

    def test_sold_out_detail_uses_disabled_controls_and_image_placeholder(self):
        response = self.client.get(reverse("store:product_detail", args=[self.sold_out.slug]))
        self.assertContains(response, "Out of stock")
        self.assertContains(response, "product-placeholder.svg")
        self.assertContains(response, 'type="submit" disabled')
        self.assertContains(response, 'name="quantity"')
        self.assertContains(response, 'value="1" inputmode="numeric"')
        self.assertContains(response, 'id="ordering-note"')

    def test_templates_only_cross_out_a_legitimately_higher_previous_price(self):
        # Use an unsaved object to exercise the UI guard independently of the DB constraint.
        for previous in (None, Decimal("0.00"), Decimal("50.00"), Decimal("85.00"), Decimal("95.00")):
            with self.subTest(previous=previous):
                self.charger.old_price = previous
                with patch("store.views.get_object_or_404", return_value=self.charger):
                    response = self.client.get(self.charger.get_absolute_url())
                card = render_to_string("store/includes/product_card.html", {"product": self.charger}, request=response.wsgi_request)
                for markup in (response.content.decode(), card):
                    self.assertEqual("<del>" in markup, previous == Decimal("95.00"))

    def test_search_matches_name_descriptions_and_sku_case_insensitively(self):
        for query in ("FAST CHARGER", "pocket", "lectures", "charge-42"):
            with self.subTest(query=query):
                response = self.client.get(reverse("store:product_list"), {"q": query})
                self.assertEqual(list(response.context["page_obj"]), [self.charger])
                self.assertContains(response, "Search results for")

    def test_search_never_exposes_hidden_products(self):
        response = self.client.get(reverse("store:product_list"), {"q": "charger"})
        self.assertEqual(list(response.context["page_obj"]), [self.charger])
        self.assertNotContains(response, self.unavailable.name)
        self.assertNotContains(response, self.hidden.name)

    def test_search_trims_whitespace_and_handles_no_results(self):
        response = self.client.get(reverse("store:product_list"), {"q": "  charger  "})
        self.assertEqual(response.context["query"], "charger")
        self.assertEqual(list(response.context["page_obj"]), [self.charger])
        response = self.client.get(reverse("store:product_list"), {"q": "nonexistent item"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No results for “nonexistent item”")
        self.assertContains(response, "Clear search")
        self.assertNotContains(response, "Browse all products")
        self.assertEqual(response.context["page_obj"].paginator.count, 0)

    def test_search_and_product_descriptions_are_html_escaped(self):
        script = '<script>alert("unsafe")</script>'
        response = self.client.get(reverse("store:product_list"), {"q": script})
        self.assertNotContains(response, script)
        self.assertContains(response, "&lt;script&gt;")
        self.charger.description = script
        self.charger.save()
        response = self.client.get(reverse("store:product_detail", args=[self.charger.slug]))
        self.assertNotContains(response, script)
        self.assertContains(response, "&lt;script&gt;")

    def test_pagination_has_twelve_products_and_preserves_encoded_search(self):
        Product.objects.bulk_create([
            Product(category=self.accessories, name=f"Campus & Cable {i:02}",
                    slug=f"campus-cable-{i}", sku=f"PAGE-{i}", price="12.00")
            for i in range(13)
        ])
        response = self.client.get(reverse("store:product_list"), {"q": "Campus & Cable"})
        self.assertEqual(len(response.context["page_obj"]), 12)
        self.assertContains(response, "?q=Campus+%26+Cable&amp;page=2")
        next_page = self.client.get(reverse("store:product_list"), {"q": "Campus & Cable", "page": 2})
        self.assertEqual(len(next_page.context["page_obj"]), 1)
        self.assertFalse(set(response.context["page_obj"]) & set(next_page.context["page_obj"]))

    def test_invalid_page_values_are_handled_gracefully(self):
        for value in ("invalid", "-1", "99999"):
            with self.subTest(value=value):
                response = self.client.get(reverse("store:product_list"), {"page": value})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["page_obj"].number, 1)

    def test_books_uses_existing_product_model_and_configured_category_slug(self):
        response = self.client.get(reverse("store:books"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["page_obj"]), [self.book])
        with self.settings(BOOKS_CATEGORY_SLUG=self.accessories.slug):
            response = self.client.get(reverse("store:books"))
            self.assertEqual(set(response.context["page_obj"]), {self.charger, self.sold_out})

    def test_books_falls_back_to_active_category_name(self):
        self.books_category.slug = "reading"
        self.books_category.name = "Books"
        self.books_category.save()
        response = self.client.get(reverse("store:books"))
        self.assertEqual(list(response.context["page_obj"]), [self.book])

    def test_missing_or_inactive_books_category_is_a_graceful_empty_page(self):
        self.books_category.is_active = False
        self.books_category.save()
        response = self.client.get(reverse("store:books"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["page_obj"]), [])
        self.assertContains(response, "Your next chapter is on its way")
        self.book.delete()
        self.books_category.delete()
        response = self.client.get(reverse("store:books"))
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["category"])

    def test_empty_shop_and_empty_category_have_helpful_states(self):
        Product.objects.all().delete()
        self.assertContains(self.client.get(reverse("store:product_list")), "No products found")
        self.assertContains(self.client.get(reverse("store:product_list")), "View all products")
        self.assertContains(self.client.get(reverse("store:category", args=[self.accessories.slug])), "This collection is getting ready")

    def test_product_card_queries_do_not_grow_per_product(self):
        # The shared footer adds one BusinessContact lookup, independent of product count.
        with self.assertNumQueries(4):
            response = self.client.get(reverse("store:product_list"))
            self.assertEqual(response.status_code, 200)
        with self.assertNumQueries(3):
            response = self.client.get(reverse("store:product_detail", args=[self.charger.slug]))
            self.assertEqual(response.status_code, 200)

    def test_catalog_routes_remain_read_only(self):
        for url in (reverse("store:product_list"), reverse("store:books"),
                    reverse("store:product_detail", args=[self.charger.slug])):
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url, {"quantity": 1}).status_code, 405)

    def test_legacy_department_urls_redirect_to_categories_and_keep_hidden_inventory_private(self):
        audio = Category.objects.create(name="Audio", parent=self.accessories)
        earbuds = Product.objects.create(category=audio, name="Earbuds", sku="AUDIO", price="50.00")
        url = reverse("store:department", args=["accessories"])
        response = self.client.get(url)
        category_url = reverse("store:category", args=[self.accessories.slug])
        self.assertRedirects(response, category_url, status_code=301, fetch_redirect_response=False)
        response = self.client.get(url, {"q": "charge-42"})
        self.assertRedirects(
            response,
            f"{category_url}?q=charge-42",
            status_code=301,
            fetch_redirect_response=False,
        )
        response = self.client.get(category_url)
        self.assertEqual(set(response.context["page_obj"]), {self.charger, self.sold_out, earbuds})
        audio.is_active = False
        audio.save()
        response = self.client.get(category_url)
        self.assertEqual(set(response.context["page_obj"]), {self.charger, self.sold_out})
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_legacy_department_urls_require_matching_database_categories(self):
        for slug in ("laptops", "phones", "electricals"):
            with self.subTest(slug=slug):
                response = self.client.get(reverse("store:department", args=[slug]))
                self.assertEqual(response.status_code, 404)
        self.assertEqual(self.client.get(reverse("store:department", args=["unknown"])).status_code, 404)

    def test_sort_and_stock_filters_preserve_visibility_and_search(self):
        url = reverse("store:product_list")
        response = self.client.get(url, {"sort": "price_low", "in_stock": "1"})
        self.assertEqual(list(response.context["page_obj"]), [self.book, self.charger])
        response = self.client.get(url, {"sort": "price_high"})
        self.assertEqual(list(response.context["page_obj"]), [self.sold_out, self.charger, self.book])
        response = self.client.get(url, {"q": "charger", "sort": "newest", "in_stock": "1"})
        self.assertEqual(list(response.context["page_obj"]), [self.charger])
        self.assertContains(response, 'name="q" value="charger"')
        response = self.client.get(url, {"sort": "invalid-field"})
        self.assertEqual(response.context["sort"], "name")

    def test_pagination_keeps_stock_filter_sort_and_query(self):
        Product.objects.bulk_create([
            Product(category=self.accessories, name=f"Cable {i}", sku=f"FILTER-{i}",
                    slug=f"filter-{i}", price="10.00", stock=2)
            for i in range(13)
        ])
        response = self.client.get(reverse("store:product_list"), {
            "q": "Cable", "sort": "price_high", "in_stock": "1",
        })
        self.assertContains(response, "q=Cable&amp;sort=price_high&amp;in_stock=1&amp;page=2")

    def test_books_includes_active_study_materials_even_without_books_category(self):
        study = Category.objects.create(name="Study Materials")
        notebook = Product.objects.create(category=study, name="Notebook", sku="STUDY-1", price="20.00")
        url = reverse("store:books")
        self.assertEqual(set(self.client.get(url).context["page_obj"]), {self.book, notebook})
        self.books_category.is_active = False
        self.books_category.save()
        self.assertEqual(list(self.client.get(url).context["page_obj"]), [notebook])
        study.is_active = False
        study.save()
        self.assertEqual(list(self.client.get(url).context["page_obj"]), [])

    def test_related_products_are_visible_same_category_and_exclude_current_product(self):
        response = self.client.get(self.charger.get_absolute_url())
        self.assertEqual(list(response.context["related_products"]), [self.sold_out])
        self.assertEqual(response.context["nav_section"], "shop")
        self.assertNotContains(response, self.unavailable.name)
        self.assertNotContains(response, self.hidden.name)

    def test_uploaded_photo_is_used_and_demo_inventory_is_labelled(self):
        self.charger.image = "products/owner-charger.jpg"
        self.charger.sku = "DEMO-CHARGER"
        self.charger.save()
        response = self.client.get(self.charger.get_absolute_url())
        self.assertContains(response, self.charger.image.url)
        self.assertContains(response, "Sample listing for preview. Price and stock are illustrative.")

    def test_unknown_stock_is_labelled_and_excluded_from_in_stock_filter(self):
        self.charger.stock = None
        self.charger.save()
        response = self.client.get(self.charger.get_absolute_url())
        self.assertContains(response, "Availability to be confirmed")
        self.assertContains(response, "Availability pending")
        response = self.client.get(reverse("store:product_list"), {"in_stock": "1"})
        self.assertEqual(list(response.context["page_obj"]), [self.book])
