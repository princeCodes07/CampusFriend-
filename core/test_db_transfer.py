import hashlib
import importlib.metadata
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import uuid

from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, transaction
from django.test import TestCase
from django.utils import timezone

from core import db_transfer as transfer
from orders.models import Order, OrderItem, Payment
from repairs.models import RepairNote, RepairNotification, RepairPayment, RepairRequest, RepairStatusHistory
from store.models import Category, Product


class DatabaseTransferTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        # Build a source within a savepoint, then restore the pristine target.
        with transaction.atomic():
            group = Group.objects.create(name='Test operators')
            permission = Permission.objects.create(
                codename='special_transfer_access', name='Custom permission',
                content_type=ContentType.objects.get_for_model(Product),
            )
            group.permissions.add(permission)
            user = User.objects.create_user('transfer-user', password='test-only-password', pk=123)
            user.groups.add(group)
            user.user_permissions.add(permission)
            parent = Category.objects.create(name='Parent', pk=80)
            child = Category.objects.create(name='Child', parent=parent, pk=81)
            product = Product.objects.create(category=child, name='Transfer product', sku='TRANSFER', price='12.34', stock=None, pk=234)
            order = Order.objects.create(guest_id=uuid.uuid4(), checkout_token=uuid.uuid4(), customer_name='Test', customer_phone='000', subtotal='24.68')
            OrderItem.objects.create(order=order, product=product, product_name='Historical name', sku='HISTORICAL', unit_price='12.34', quantity=2, line_total='24.68')
            Payment.objects.create(order=order, reference='transfer-payment', amount='24.68', customer_email='test@example.test', provider_response={'sample': [1, True, None]})
            repair = RepairRequest.objects.create(request_type='PHONE_SPECIAL_PROBLEM', customer_name='Test', phone_number='000', guest_session_id='test-session')
            RepairNote.objects.create(repair_request=repair, note='Test history')
            RepairStatusHistory.objects.create(repair_request=repair, status=repair.status)
            RepairPayment.objects.create(repair_request=repair, amount='25.50', currency='GHS')
            RepairNotification.objects.create(repair=repair, channel='EMAIL', event='test', recipient='test@example.test', message='Test notification')
            Session.objects.create(session_key='test-preserved-session', session_data='opaque-test-value', expire_date=timezone.now())
            self.expected = transfer.records()
            self.write_bundle(self.expected)
            transaction.set_rollback(True)

    def write_bundle(self, rows):
        payload = transfer.encoded(rows).encode('utf-8')
        (self.bundle / 'fixture.json').write_bytes(payload)
        manifest = {
            'format': 1, 'django': importlib.metadata.version('Django'),
            'sha256': hashlib.sha256(payload).hexdigest(),
            'models': sorted(m._meta.label_lower for m in transfer.models_in_order()),
            'migrations': transfer.migration_state('default'),
        }
        (self.bundle / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    def run_import(self, **kwargs):
        return transfer.import_bundle(self.bundle, require_postgres=False, **kwargs)

    def test_round_trip_preserves_records_permissions_and_is_repeatable(self):
        self.run_import(commit=True)
        transfer.verify_bundle(self.bundle)
        self.assertTrue(User.objects.get(pk=123).check_password('test-only-password'))
        self.assertTrue(User.objects.get(pk=123).has_perm('store.special_transfer_access'))
        self.assertEqual(OrderItem.objects.get().product_id, 234)
        self.assertEqual(Product.objects.get(pk=234).category.parent_id, 80)
        self.assertIsNone(Order.objects.get().total)
        self.assertEqual(Session.objects.count(), 1)
        self.assertIn('without rewriting', self.run_import(commit=True))
        new_product = Product.objects.create(category_id=81, name='Next product', sku='NEXT', price='1.00')
        self.assertGreater(new_product.pk, 234)

    def test_default_dry_run_rolls_back(self):
        before = transfer.canonical(transfer.records())
        self.assertIn('rolled back', self.run_import())
        self.assertEqual(transfer.canonical(transfer.records()), before)

    def test_occupied_or_changed_target_is_never_overwritten(self):
        Category.objects.create(name='Existing work')
        before = transfer.canonical(transfer.records())
        with self.assertRaisesMessage(CommandError, 'existing or changed'):
            self.run_import(commit=True)
        self.assertEqual(transfer.canonical(transfer.records()), before)

    def test_rerun_after_user_edit_is_refused(self):
        self.run_import(commit=True)
        Product.objects.filter(pk=234).update(price='14.00')
        with self.assertRaises(CommandError):
            self.run_import(commit=True)
        self.assertEqual(str(Product.objects.get(pk=234).price), '14.00')

    def test_checksum_and_schema_mismatch_refused(self):
        with (self.bundle / 'fixture.json').open('ab') as file:
            file.write(b' ')
        with self.assertRaisesMessage(CommandError, 'checksum'):
            self.run_import(commit=True)
        self.write_bundle(self.expected)
        path = self.bundle / 'manifest.json'
        manifest = json.loads(path.read_text())
        manifest['migrations'] = []
        path.write_text(json.dumps(manifest))
        with self.assertRaisesMessage(CommandError, 'histories differ'):
            self.run_import(commit=True)

    def test_verification_failure_rolls_back_everything(self):
        before = transfer.canonical(transfer.records())
        with patch.object(transfer, 'verify_rows', side_effect=CommandError('Verification failed')):
            with self.assertRaises(CommandError):
                self.run_import(commit=True)
        self.assertEqual(transfer.canonical(transfer.records()), before)

    def test_constraint_failure_rolls_back_everything(self):
        broken = json.loads(json.dumps(self.expected))
        for row in broken:
            if row['model'] == 'store.product':
                row['fields']['category'] = 999999
        self.write_bundle(broken)
        before = transfer.canonical(transfer.records())
        with self.assertRaises(Exception):
            self.run_import(commit=True)
        self.assertEqual(transfer.canonical(transfer.records()), before)

    def test_cli_never_imports_to_sqlite(self):
        if connection.vendor == 'sqlite':
            with self.assertRaisesMessage(CommandError, 'requires PostgreSQL'):
                call_command('transfer_database', 'import', bundle=str(self.bundle), commit=True)

    def test_cli_redacts_driver_errors(self):
        with patch('core.management.commands.transfer_database.import_bundle', side_effect=RuntimeError('private-url-and-customer-data')):
            with self.assertRaises(CommandError) as caught:
                call_command('transfer_database', 'import', bundle=str(self.bundle))
        self.assertNotIn('private-url', str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)
