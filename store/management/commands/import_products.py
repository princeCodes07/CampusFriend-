"""Load owner-supplied catalog data, validating the entire import atomically."""

import json
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from store.models import Category, Product


class Command(BaseCommand):
    help = "Create or update products by SKU from catalog/products.json. Upload photos in Admin."

    def add_arguments(self, parser):
        parser.add_argument("path", type=Path)
        parser.add_argument("--dry-run", action="store_true", help="Validate without saving changes.")

    def handle(self, *args, **options):
        try:
            document = json.loads(options["path"].read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, ValueError) as error:
            raise CommandError(f"Cannot read product file: {error}") from error
        if not isinstance(document, dict) or not isinstance(document.get("products"), list):
            raise CommandError('Expected an object containing a "products" list. See catalog/README.md.')
        rows = document["products"]
        if not rows:
            self.stdout.write("No products to import. Add your real entries to catalog/products.json.")
            return

        required = {"sku", "name", "category", "price", "stock"}
        optional = {"old_price", "short_description", "description", "is_available", "is_featured"}
        seen = set()
        created = updated = 0
        row_number = 0
        try:
            with transaction.atomic():
                for row_number, row in enumerate(rows, start=1):
                    if not isinstance(row, dict):
                        raise CommandError(f"Product {row_number} must be an object.")
                    missing = required - row.keys()
                    unknown = row.keys() - required - optional
                    if missing or unknown:
                        raise CommandError(
                            f"Product {row_number}: missing fields {sorted(missing)}; "
                            f"unknown fields {sorted(unknown)}. Photos are uploaded in Admin."
                        )
                    for field in ("sku", "name", "category"):
                        if not isinstance(row[field], str) or not row[field].strip():
                            raise CommandError(f"Product {row_number}: {field} must be nonempty text.")
                    for field in ("short_description", "description"):
                        if field in row and not isinstance(row[field], str):
                            raise CommandError(f"Product {row_number}: {field} must be text.")
                    if row["stock"] is not None and (type(row["stock"]) is not int or row["stock"] < 0):
                        raise CommandError(f"Product {row_number}: stock must be a nonnegative integer or null.")
                    for field in ("is_available", "is_featured"):
                        if field in row and type(row[field]) is not bool:
                            raise CommandError(f"Product {row_number}: {field} must be true or false.")
                    for field in ("price", "old_price"):
                        if field in row and row[field] is not None:
                            if type(row[field]) not in (str, int, float):
                                raise CommandError(f"Product {row_number}: {field} must be a decimal amount.")
                            row[field] = str(row[field])

                    sku = row["sku"].strip()
                    if sku in seen:
                        raise CommandError(f"Product {row_number}: duplicate SKU {sku!r} in this file.")
                    seen.add(sku)
                    category_slug = row["category"].strip()

                    category = (
                        Category.objects
                        .filter(slug=category_slug)
                        .first()
                    )

                    if category is None:
                        raise CommandError(
                            (
                                f"Product {row_number}: "
                                f"unknown category {category_slug!r}. "
                                "Create/organize Store categories in Django Admin "
                                "or run `python manage.py setup_catalog` first."
                            )
                        )

                    product = Product.objects.filter(sku=sku).first()
                    is_new = product is None
                    if is_new:
                        product = Product(sku=sku, is_available=False)
                    for field, value in row.items():
                        if field not in ("sku", "category"):
                            setattr(product, field, value.strip() if field == "name" else value)
                    product.category = category
                    product.full_clean()
                    product.save()
                    created += is_new
                    updated += not is_new
                if options["dry_run"]:
                    transaction.set_rollback(True)
        except (ValidationError, IntegrityError) as error:
            raise CommandError(f"Product {row_number}: {error}. No changes were saved.") from error
        if options["dry_run"]:
            self.stdout.write(self.style.SUCCESS(
                f"Validated: {created} new, {updated} existing. Dry run: no changes saved."
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f"Imported: {created} created, {updated} updated. Existing photos and URLs preserved."
            ))
