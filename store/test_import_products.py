import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management import call_command, CommandError
from django.test import TestCase

from .models import Category, Product


class ImportProductsTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Accessories")
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "products.json"

    def row(self, **changes):
        values = {
            "sku": "OWNER-001", "name": "Owner's charger", "category": "accessories",
            "price": "85.00", "stock": 3,
        }
        values.update(changes)
        return values

    def run_import(self, rows, **options):
        self.path.write_text(json.dumps({"products": rows}), encoding="utf-8")
        output = StringIO()
        call_command("import_products", str(self.path), stdout=output, **options)
        return output.getvalue()

    def test_import_creates_draft_and_reimports_by_sku_preserving_photo_url_and_description(self):
        self.run_import([self.row(description="Original description")])
        product = Product.objects.get(sku="OWNER-001")
        self.assertFalse(product.is_available)
        product.image = "products/existing-owner-photo.jpg"
        product.save()
        slug = product.slug
        self.run_import([self.row(name="Renamed charger", price="90.00", is_available=True)])
        product.refresh_from_db()
        self.assertEqual(Product.objects.count(), 1)
        self.assertEqual(str(product.price), "90.00")
        self.assertEqual(product.slug, slug)
        self.assertEqual(product.image.name, "products/existing-owner-photo.jpg")
        self.assertEqual(product.description, "Original description")
        self.assertTrue(product.is_available)

    def test_dry_run_does_not_save_products_categories_or_existing_changes(self):
        output = self.run_import([self.row()], dry_run=True)
        self.assertIn("no changes saved", output)
        self.assertEqual(list(Category.objects.all()), [self.category])
        self.assertFalse(Product.objects.exists())
        self.run_import([self.row()])
        self.run_import([self.row(price="40.00")], dry_run=True)
        self.assertEqual(str(Product.objects.get().price), "85.00")

    def test_bad_later_row_rolls_back_the_entire_import(self):
        with self.assertRaises(CommandError):
            self.run_import([self.row(), self.row(sku="BAD-002", price="-1.00")])
        self.assertFalse(Product.objects.exists())
        self.assertEqual(list(Category.objects.all()), [self.category])

    def test_invalid_types_unknown_fields_and_bad_prices_are_rejected(self):
        for changes in (
            {"stock": 1.5}, {"stock": True}, {"is_available": "false"},
            {"is_featured": 1}, {"price": "NaN"}, {"price": "1.234"},
            {"price": None}, {"category": "accessorie-typo"}, {"image": "photo.jpg"},
            {"name": ""}, {"description": None},
            {"old_price": "0.00"}, {"old_price": "80.00"}, {"old_price": "85.00"},
        ):
            with self.subTest(changes=changes), self.assertRaises(CommandError):
                self.run_import([self.row(**changes)])
        self.assertFalse(Product.objects.exists())
        self.assertEqual(list(Category.objects.all()), [self.category])

    def test_duplicate_sku_is_rejected_without_saving(self):
        with self.assertRaises(CommandError):
            self.run_import([self.row(), self.row(name="Another product")])
        self.assertFalse(Product.objects.exists())

    def test_import_respects_inactive_categories_and_unlisted_products(self):
        self.category.is_active = False
        self.category.save()
        existing = Product.objects.create(category=self.category, name="Existing", sku="EXISTING", price="5.00")
        self.run_import([self.row(is_available=True)])
        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)
        self.assertTrue(Product.objects.filter(pk=existing.pk).exists())

    def test_empty_file_is_a_noop_and_invalid_json_is_reported(self):
        self.assertIn("No products", self.run_import([]))
        for content in ("not json", "[]", '{"products": "wrong"}'):
            self.path.write_text(content, encoding="utf-8")
            with self.assertRaises(CommandError):
                call_command("import_products", str(self.path), stdout=StringIO())

    def test_unknown_stock_can_be_imported_without_inventing_a_quantity(self):
        self.run_import([self.row(stock=None, is_available=True)])
        product = Product.objects.get(sku="OWNER-001")
        self.assertIsNone(product.stock)
        self.assertFalse(product.is_in_stock)
        self.assertTrue(product.is_available)

    def test_price_increase_requires_clearing_or_raising_the_previous_price(self):
        self.run_import([self.row(old_price="95.00")])
        with self.assertRaises(CommandError):
            self.run_import([self.row(price="100.00")])
        product = Product.objects.get(sku="OWNER-001")
        self.assertEqual(str(product.price), "85.00")
        self.assertEqual(str(product.old_price), "95.00")
        self.run_import([self.row(price="100.00", old_price=None)])
        product.refresh_from_db()
        self.assertEqual(str(product.price), "100.00")
        self.assertIsNone(product.old_price)
