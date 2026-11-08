"""Synthetic records only. These tests never load the owner's catalog bundle."""

import copy
import base64
from contextlib import redirect_stdout
import gzip
import hashlib
import io
import os
from unittest.mock import patch

import django
from django.contrib.auth import get_user_model
from django.core.management.base import CommandError
from django.test import TransactionTestCase

from core.catalog_transfer import LABELS, load_catalog, selected_rows, table_counts, transfer, validate_rows
from core.db_transfer import encoded, migration_state
from core.models import BusinessContact
from store.models import Category, Product


class CatalogTransferTests(TransactionTestCase):
    def setUp(self):
        self.parent = Category.objects.create(pk=101, name="Synthetic parent", slug="synthetic-parent")
        self.child = Category.objects.create(pk=102, name="Synthetic child", slug="synthetic-child", parent=self.parent)
        self.product = Product.objects.create(pk=201, category=self.child, name="Synthetic product", slug="synthetic-product",
                                              sku="SYNTHETIC-201", price="12.34", stock=None, image="products/synthetic.jpg")
        self.contact = BusinessContact.objects.create(pk=301, instagram_url="https://example.test/social")
        self.document = {"format": "campusfriend-catalog-v1", "django": django.get_version(),
                         "migrations": migration_state("default"), "review": {"reviewed": True},
                         "rows": [row for label in LABELS for row in selected_rows("default", label)]}
        self.product.delete()
        self.child.delete()
        self.parent.delete()
        self.contact.delete()
        self.user = get_user_model().objects.create(username="synthetic-existing-admin")

    def transfer(self, mode="check", document=None):
        return transfer(document or self.document, mode=mode, allow_sqlite_tests=True)

    def test_check_is_read_only_and_reports_expected_counts(self):
        result = self.transfer()
        self.assertEqual(result["insert_counts"], {"store.category": 2, "store.product": 1, "core.businesscontact": 1})
        self.assertEqual(Product.objects.count(), 0)

    def test_dry_run_rolls_back_every_insert(self):
        before = table_counts("default")
        result = self.transfer("dry-run")
        self.assertEqual(result["result"], "DRY_RUN_ROLLED_BACK")
        self.assertEqual(table_counts("default"), before)

    def test_commit_preserves_keys_parents_timestamps_stock_media_and_existing_data(self):
        before = table_counts("default")
        self.transfer("commit")
        self.assertEqual(Product.objects.get(pk=201).category_id, 102)
        self.assertEqual(Category.objects.get(pk=102).parent_id, 101)
        self.assertIsNone(Product.objects.get(pk=201).stock)
        self.assertEqual(Product.objects.get(pk=201).image.name, "products/synthetic.jpg")
        self.assertEqual(BusinessContact.objects.get(pk=301).instagram_url, "https://example.test/social")
        for label, count in before.items():
            if label not in LABELS:
                self.assertEqual(table_counts("default")[label], count)
        self.assertEqual(self.transfer("verify")["result"], "VERIFIED_NO_WRITES")

    def test_identical_retry_is_noop_but_changed_stock_is_refused(self):
        self.transfer("commit")
        with patch("django.db.models.Model.save_base") as save:
            self.assertEqual(self.transfer("commit")["result"], "ALREADY_IDENTICAL_NO_CHANGES")
            save.assert_not_called()
        Product.objects.filter(pk=201).update(stock=99)
        with self.assertRaisesRegex(CommandError, "EXISTING_PRIMARY_KEY_DIFFERS"):
            self.transfer("commit")
        self.assertEqual(Product.objects.get(pk=201).stock, 99)

    def test_same_sku_different_pk_refused_without_updates(self):
        category = Category.objects.create(pk=900, name="Existing category", slug="existing-category")
        Product.objects.create(pk=901, category=category, name="Existing", slug="existing", sku="SYNTHETIC-201", price="1.00")
        with self.assertRaisesRegex(CommandError, "EXISTING_UNIQUE_VALUE_COLLISION"):
            self.transfer("commit")
        self.assertEqual(Product.objects.count(), 1)
        self.assertFalse(Category.objects.filter(pk=101).exists())

    def test_existing_business_contact_refused(self):
        BusinessContact.objects.create(pk=1, instagram_url="https://example.test/existing")
        with self.assertRaisesRegex(CommandError, "EXISTING_BUSINESS_CONTACT_CONFLICT"):
            self.transfer("commit")
        self.assertEqual(BusinessContact.objects.count(), 1)

    def test_unrelated_existing_catalog_rows_survive(self):
        Category.objects.create(pk=900, name="Existing category", slug="existing-category")
        self.transfer("commit")
        self.assertEqual(Category.objects.get(pk=900).name, "Existing category")

    def test_missing_parent_and_category_cycles_rejected(self):
        bad = copy.deepcopy(self.document["rows"])
        bad[0]["fields"]["parent"] = 102
        with self.assertRaisesRegex(CommandError, "MISSING_PARENT_OR_CATEGORY_CYCLE"):
            validate_rows(bad)
        bad[0]["fields"]["parent"] = 999
        with self.assertRaises(CommandError):
            validate_rows(bad)

    def test_scope_and_review_guards(self):
        bad = copy.deepcopy(self.document)
        bad["rows"][0]["model"] = "auth.user"
        with self.assertRaisesRegex(CommandError, "OUT_OF_SCOPE_MODEL_REFUSED"):
            self.transfer(document=bad)
        bad = copy.deepcopy(self.document)
        bad["review"]["reviewed"] = False
        with self.assertRaisesRegex(CommandError, "SELECTION_REVIEW_REQUIRED"):
            self.transfer("commit", bad)
        with self.assertRaisesRegex(CommandError, "POSTGRESQL_REQUIRED"):
            transfer(self.document, mode="commit")

    def test_checksum_and_record_shape_guard(self):
        payload = encoded(self.document).encode()
        digest = hashlib.sha256(payload).hexdigest()
        self.assertEqual(load_catalog(payload, digest)["format"], "campusfriend-catalog-v1")
        with self.assertRaisesRegex(CommandError, "BUNDLE_CHECKSUM_MISMATCH"):
            load_catalog(payload + b' ', digest)
        bad = copy.deepcopy(self.document["rows"])
        bad[0]["fields"]["unexpected"] = "value"
        with self.assertRaisesRegex(CommandError, "FIELD_SET_MISMATCH"):
            validate_rows(bad)

    def test_mid_import_error_rolls_back_all_rows(self):
        with patch("core.catalog_transfer.verify_selected", side_effect=CommandError("SYNTHETIC_FAILURE")):
            with self.assertRaises(CommandError):
                self.transfer("commit")
        self.assertEqual(Category.objects.count(), 0)
        self.assertEqual(Product.objects.count(), 0)

    def test_different_migration_history_refused_before_writes(self):
        bad = copy.deepcopy(self.document)
        bad["migrations"] = []
        with self.assertRaisesRegex(CommandError, "MIGRATION_HISTORY_MISMATCH"):
            self.transfer("commit", bad)
        self.assertEqual(Category.objects.count(), 0)

    def test_cli_requires_exact_approval_before_even_opening_target(self):
        from catalog_transfer import main
        payload = encoded(self.document).encode()
        digest = hashlib.sha256(payload).hexdigest()
        env = {"CATALOG_BUNDLE_GZIP_B64": base64.b64encode(gzip.compress(payload)).decode(),
               "CATALOG_BUNDLE_SHA256": digest, "CATALOG_IMPORT_APPROVED_SHA256": ""}
        for action in ["dry-run", "commit"]:
            with self.subTest(action=action), patch.dict(os.environ, env), \
                 patch("render_postgres.validate_target") as target, redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([action]), 1)
                target.assert_not_called()
                self.assertIn("EXPLICIT_IMPORT_APPROVAL_REQUIRED", output.getvalue())
                self.assertNotIn(env["CATALOG_BUNDLE_GZIP_B64"], output.getvalue())
