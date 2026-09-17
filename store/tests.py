from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import Category, Product


class CatalogModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Accessories")

    def make_product(self, **overrides):
        values = {
            "category": self.category,
            "name": "USB cable",
            "sku": "CABLE-001",
            "price": Decimal("25.50"),
        }
        values.update(overrides)
        return Product.objects.create(**values)

    def test_defaults_strings_ordering_and_timestamps(self):
        product = self.make_product()
        books = Category.objects.create(name="Books")
        adapter = self.make_product(name="Adapter", sku="ADAPTER-001")
        self.assertEqual(str(self.category), "Accessories")
        self.assertEqual(str(product), "USB cable (CABLE-001)")
        self.assertEqual(list(Category.objects.all()), [self.category, books])
        self.assertEqual(list(Product.objects.all()), [adapter, product])
        self.assertTrue(self.category.is_active)
        self.assertTrue(product.is_available)
        self.assertFalse(product.is_featured)
        self.assertEqual(product.stock, 0)
        self.assertIsNone(product.old_price)
        self.assertFalse(product.image)
        for item in (self.category, product):
            self.assertIsNotNone(item.created_at)
            self.assertIsNotNone(item.updated_at)

    def test_missing_slugs_handle_existing_collisions(self):
        first_category = Category.objects.create(name="USB C")
        second_category = Category.objects.create(name="USB-C")
        first_product = self.make_product()
        second_product = self.make_product(sku="CABLE-002")
        self.assertEqual(first_category.slug, "usb-c")
        self.assertEqual(second_category.slug, "usb-c-2")
        self.assertEqual(first_product.slug, "usb-cable")
        self.assertEqual(second_product.slug, "usb-cable-2")

    def test_slug_fallback_when_name_has_no_ascii_slug(self):
        first = Category.objects.create(name="书籍")
        second = Category.objects.create(name="电子")
        product = self.make_product(name="耳机")
        self.assertEqual(first.slug, "category")
        self.assertEqual(second.slug, "category-2")
        self.assertEqual(product.slug, "product")

    def test_custom_slugs_and_existing_slugs_survive_renames(self):
        category = Category.objects.create(name="Chargers", slug="charging")
        product = self.make_product(slug="custom-cable")
        for item in (category, product, self.category):
            original_slug = item.slug
            item.name += " renamed"
            item.save()
            item.refresh_from_db()
            self.assertEqual(item.slug, original_slug)

    def test_cleared_slug_is_saved_during_partial_update(self):
        product = self.make_product()
        for item in (self.category, product):
            item.slug = ""
            item.name = "Renamed item"
            item.save(update_fields={"name"})
            item.refresh_from_db()
            self.assertEqual(item.slug, "renamed-item")

    def test_unique_names_slugs_and_skus_are_database_enforced(self):
        product = self.make_product()
        cases = [
            (Category, {"name": self.category.name, "slug": "other-category"}),
            (Category, {"name": "Other category", "slug": self.category.slug}),
            (Product, {"category": self.category, "name": "Other product",
                       "sku": product.sku, "slug": "other-product", "price": "1.00"}),
            (Product, {"category": self.category, "name": "Other product",
                       "sku": "OTHER-001", "slug": product.slug, "price": "1.00"}),
        ]
        for model, values in cases:
            with self.subTest(model=model.__name__, values=values):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    model.objects.create(**values)

    def test_negative_prices_and_stock_fail_model_validation(self):
        for field in ("price", "old_price", "stock"):
            with self.subTest(field=field):
                product = Product(
                    category=self.category, name="Cable", sku="INVALID", price="1.00"
                )
                setattr(product, field, -1)
                with self.assertRaises(ValidationError) as error:
                    product.full_clean()
                self.assertIn(field, error.exception.message_dict)

    def test_negative_prices_and_stock_fail_direct_database_updates(self):
        product = self.make_product()
        for field in ("price", "old_price", "stock"):
            with self.subTest(field=field):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    Product.objects.filter(pk=product.pk).update(**{field: -1})
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("25.50"))
        self.assertIsNone(product.old_price)
        self.assertEqual(product.stock, 0)

    def test_zero_prices_nullable_old_price_and_decimal_round_trip(self):
        product = self.make_product(price=Decimal("0.10"))
        product.full_clean()
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("0.10"))
        product.price = Decimal("0.00")
        product.old_price = Decimal("0.00")
        product.full_clean()
        product.save()
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("0.00"))
        self.assertEqual(product.old_price, Decimal("0.00"))

    def test_stock_helper_is_independent_of_visibility(self):
        product = self.make_product(stock=1, is_available=False)
        self.category.is_active = False
        self.category.save()
        self.assertTrue(product.is_in_stock)
        product.stock = 0
        self.assertFalse(product.is_in_stock)

    def test_category_with_products_cannot_be_deleted(self):
        product = self.make_product()
        with self.assertRaises(ProtectedError):
            self.category.delete()
        product.refresh_from_db()
        self.assertEqual(product.category, self.category)


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CatalogAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin_user = get_user_model().objects.create_superuser(
            username="catalog-admin", email="catalog-admin@example.com", password=None
        )
        cls.category = Category.objects.create(name="Accessories")

    def setUp(self):
        self.client.force_login(self.admin_user)
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        media_settings = self.settings(MEDIA_ROOT=self.media_directory.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def product_data(self, **overrides):
        data = {
            "name": "USB cable",
            "category": str(self.category.pk),
            "sku": "ADMIN-001",
            "slug": "",
            "price": "25.50",
            "old_price": "",
            "stock": "3",
            "is_available": "on",
            "_save": "Save",
        }
        data.update(overrides)
        return data

    def test_category_can_be_created_and_edited(self):
        response = self.client.post(reverse("admin:store_category_add"), {
            "name": "Books", "slug": "", "is_active": "on", "_save": "Save",
        })
        self.assertRedirects(response, reverse("admin:store_category_changelist"))
        category = Category.objects.get(name="Books")
        self.assertEqual(category.slug, "books")
        response = self.client.post(
            reverse("admin:store_category_change", args=[category.pk]),
            {"name": "Personal-development books", "slug": "books", "_save": "Save"},
        )
        self.assertEqual(response.status_code, 302)
        category.refresh_from_db()
        self.assertFalse(category.is_active)
        self.assertEqual(category.name, "Personal-development books")

    def test_product_can_be_created_with_image_and_edited(self):
        buffer = BytesIO()
        Image.new("RGB", (2, 2), color="white").save(buffer, format="PNG")
        upload = SimpleUploadedFile("cable.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post(
            reverse("admin:store_product_add"), self.product_data(image=upload)
        )
        self.assertRedirects(response, reverse("admin:store_product_changelist"))
        product = Product.objects.get(sku="ADMIN-001")
        self.assertEqual(product.price, Decimal("25.50"))
        self.assertEqual(product.slug, "usb-cable")
        self.assertIsNone(product.old_price)
        self.assertTrue(Path(product.image.path).is_file())
        self.assertTrue(product.image.url.startswith("/media/products/"))
        response = self.client.post(
            reverse("admin:store_product_change", args=[product.pk]),
            self.product_data(
                slug=product.slug, price="30.00", old_price="35.00", stock="0",
                is_available="", is_featured="on",
            ),
        )
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.price, Decimal("30.00"))
        self.assertEqual(product.old_price, Decimal("35.00"))
        self.assertFalse(product.is_in_stock)
        self.assertFalse(product.is_available)
        self.assertTrue(product.is_featured)

    def test_product_form_rejects_negative_and_fractional_stock_values(self):
        for field, value in [("price", "-0.01"), ("old_price", "-1.00"),
                             ("stock", "-1"), ("stock", "1.5")]:
            with self.subTest(field=field, value=value):
                response = self.client.post(
                    reverse("admin:store_product_add"),
                    self.product_data(**{field: value}),
                )
                self.assertEqual(response.status_code, 200)
                self.assertIn(field, response.context["adminform"].form.errors)
                self.assertEqual(Product.objects.count(), 0)

    def test_product_form_reports_duplicate_sku_and_slug(self):
        product = Product.objects.create(
            category=self.category, name="Existing", sku="ADMIN-001", price="1.00"
        )
        response = self.client.post(
            reverse("admin:store_product_add"), self.product_data(slug=product.slug)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("sku", response.context["adminform"].form.errors)
        self.assertIn("slug", response.context["adminform"].form.errors)
        self.assertEqual(Product.objects.count(), 1)

    def test_non_image_upload_is_rejected(self):
        upload = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        response = self.client.post(
            reverse("admin:store_product_add"), self.product_data(image=upload)
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("image", response.context["adminform"].form.errors)
        self.assertFalse(Product.objects.exists())

    def test_category_search_and_active_filter(self):
        inactive = Category.objects.create(name="Books", is_active=False)
        for query in ({"q": "Books"}, {"is_active__exact": "0"}):
            with self.subTest(query=query):
                response = self.client.get(reverse("admin:store_category_changelist"), query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["cl"].queryset), [inactive])

    def test_product_search_and_filters(self):
        books = Category.objects.create(name="Books")
        cable = Product.objects.create(
            category=self.category, name="USB cable", sku="SEARCH-CABLE",
            price="25.50", is_available=False, is_featured=True,
        )
        Product.objects.create(category=books, name="Study book", sku="BOOK", price="10.00")
        for query in ({"q": "SEARCH-CABLE"}, {"q": "Accessories"},
                      {"category__id__exact": str(self.category.pk)},
                      {"is_available__exact": "0"}, {"is_featured__exact": "1"}):
            with self.subTest(query=query):
                response = self.client.get(reverse("admin:store_product_changelist"), query)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["cl"].queryset), [cable])

    def test_catalog_admin_requires_login_and_model_permissions(self):
        self.client.logout()
        for model in ("category", "product"):
            response = self.client.get(reverse(f"admin:store_{model}_changelist"))
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith(reverse("admin:login")))
        staff = get_user_model().objects.create_user(username="limited-staff", is_staff=True)
        self.client.force_login(staff)
        response = self.client.post(reverse("admin:store_product_add"), self.product_data())
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Product.objects.exists())
