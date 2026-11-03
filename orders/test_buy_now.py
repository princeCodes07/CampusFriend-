from decimal import Decimal

from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import Category, Product

from .cart import CART_SESSION_KEY
from .models import Order, Payment
from .views import GUEST_SESSION_KEY, PREVIEW_SESSION_KEY


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class BuyNowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.parent = Category.objects.create(name='Store section')
        cls.category = Category.objects.create(name='Accessories', parent=cls.parent)
        cls.product = Product.objects.create(
            category=cls.category, name='Power bank', sku='BUY-NOW',
            price=Decimal('22.74'), stock=4,
        )
        cls.other = Product.objects.create(
            category=cls.category, name='Cable', sku='BUY-NOW-CABLE',
            price=Decimal('10.05'), stock=10,
        )

    def setUp(self):
        self.url = reverse('orders:cart_add', args=[self.product.pk])
        self.checkout_url = reverse('orders:checkout')

    def buy(self, quantity=1, **extra):
        return self.client.post(self.url, {'action': 'buy_now', 'quantity': quantity, **extra}, follow=True)

    def test_buy_now_preserves_existing_cart_and_merges_quantity_without_reserving_stock(self):
        self.client.post(reverse('orders:cart_add', args=[self.other.pk]), {'quantity': 2})
        self.client.post(self.url, {'quantity': 1})
        response = self.buy(2)
        self.assertRedirects(response, self.checkout_url)
        self.assertEqual(self.client.session[CART_SESSION_KEY], {
            str(self.product.pk): 3, str(self.other.pk): 2,
        })
        self.assertEqual(response.context['cart'].subtotal, Decimal('88.32'))
        self.assertContains(response, 'aria-label="Cart, 5 items"')
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
        self.assertFalse(Order.objects.exists())
        self.assertFalse(Payment.objects.exists())
        self.client.get(self.checkout_url)
        self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.product.pk)], 3)

    def test_buy_now_uses_current_catalog_prices_and_ignores_browser_totals(self):
        Product.objects.filter(pk=self.product.pk).update(price='25.10')
        response = self.buy(2, price='0.01', subtotal='0.02', total='0.02', discount='100', stock='999')
        self.assertRedirects(response, self.checkout_url)
        self.assertEqual(response.context['cart'].subtotal, Decimal('50.20'))
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 2})

    def test_buy_now_requires_post(self):
        for method in (self.client.get, self.client.head):
            response = method(self.url, {'action': 'buy_now', 'quantity': 1})
            self.assertEqual(response.status_code, 405)
        self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_buy_now_requires_valid_csrf_and_accepts_token_from_product_card(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(self.url, {'action': 'buy_now', 'quantity': 1}).status_code, 403)
        browser.get(reverse('store:product_list'))
        self.assertEqual(browser.post(self.url, {
            'action': 'buy_now', 'quantity': 1, 'csrfmiddlewaretoken': 'invalid',
        }).status_code, 403)
        self.assertNotIn(CART_SESSION_KEY, browser.session)
        response = browser.post(self.url, {
            'action': 'buy_now', 'quantity': 1, 'csrfmiddlewaretoken': browser.cookies['csrftoken'].value,
        })
        self.assertRedirects(response, self.checkout_url)
        self.assertEqual(browser.session[CART_SESSION_KEY], {str(self.product.pk): 1})

    def test_invalid_or_missing_quantity_keeps_existing_cart_and_does_not_open_checkout(self):
        self.client.post(self.url, {'quantity': 1})
        for quantity in ('', '0', '-1', '1.5', 'bad', 'NaN', 'Infinity', '2147483648', None):
            with self.subTest(quantity=quantity):
                data = {'action': 'buy_now'}
                if quantity is not None:
                    data['quantity'] = quantity
                response = self.client.post(self.url, data, follow=True)
                self.assertRedirects(response, self.product.get_absolute_url())
                self.assertContains(response, 'class="message error"')
                self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 1})
                self.assertNotIn(PREVIEW_SESSION_KEY, self.client.session)

    def test_buy_now_rejects_cumulative_overstock(self):
        self.client.post(self.url, {'quantity': 3})
        response = self.buy(2, stock=100)
        self.assertRedirects(response, self.product.get_absolute_url())
        self.assertContains(response, 'Only 4 available.')
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 3})
        self.assertRedirects(self.buy(1), self.checkout_url)
        self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.product.pk)], 4)

    def test_stale_card_cannot_buy_unconfirmed_or_sold_out_product(self):
        self.client.get(reverse('store:product_list'))
        for stock in (None, 0):
            with self.subTest(stock=stock):
                Product.objects.filter(pk=self.product.pk).update(stock=stock)
                response = self.buy()
                self.assertRedirects(response, self.product.get_absolute_url())
                self.assertContains(response, 'This product is currently unavailable')
                self.assertNotIn(CART_SESSION_KEY, self.client.session)
                self.assertNotIn(PREVIEW_SESSION_KEY, self.client.session)

    def test_hidden_product_inactive_category_or_parent_and_missing_product_are_rejected(self):
        for model, pk, field in (
            (Product, self.product.pk, 'is_available'),
            (Category, self.category.pk, 'is_active'),
            (Category, self.parent.pk, 'is_active'),
        ):
            with self.subTest(model=model, field=field):
                model.objects.filter(pk=pk).update(**{field: False})
                self.assertEqual(self.buy().status_code, 404)
                self.assertNotIn(CART_SESSION_KEY, self.client.session)
                model.objects.filter(pk=pk).update(**{field: True})
        self.product.delete()
        self.assertEqual(self.buy().status_code, 404)

    def test_redirects_are_fixed_and_normal_add_still_opens_cart(self):
        for action in ('https://example.test/checkout/', '//example.test', '/checkout/', ''):
            with self.subTest(action=action):
                response = self.client.post(self.url, {
                    'quantity': 1, 'action': action, 'next': 'https://example.test/',
                })
                self.assertRedirects(response, reverse('orders:cart_detail'))
        self.client.post(reverse('orders:cart_remove', args=[self.product.pk]))
        self.assertRedirects(self.buy(next='https://example.test/'), self.checkout_url)

    def test_buy_now_reconciles_saved_cart_and_preserves_guest_session_isolation(self):
        self.client.post(reverse('orders:cart_add', args=[self.other.pk]), {'quantity': 5})
        Product.objects.filter(pk=self.other.pk).update(stock=2)
        response = self.buy()
        self.assertContains(response, 'Your cart was updated to match current stock and availability.')
        self.assertEqual(self.client.session[CART_SESSION_KEY], {
            str(self.other.pk): 2, str(self.product.pk): 1,
        })
        guest_id = self.client.session[GUEST_SESSION_KEY]
        self.assertRedirects(self.buy(), self.checkout_url)
        self.assertEqual(self.client.session[GUEST_SESSION_KEY], guest_id)
        visitor = Client()
        visitor.post(self.url, {'quantity': 1, 'action': 'buy_now'}, follow=True)
        self.assertEqual(visitor.session[CART_SESSION_KEY], {str(self.product.pk): 1})
        self.assertNotEqual(visitor.session[GUEST_SESSION_KEY], guest_id)

    def test_buy_now_refreshes_checkout_preview_then_existing_checkout_remains_idempotent(self):
        response = self.buy()
        old_token = response.context['form']['checkout_token'].value()
        response = self.buy()
        token = response.context['form']['checkout_token'].value()
        self.assertNotEqual(token, old_token)
        data = {
            'checkout_token': token, 'customer_name': 'Test Student',
            'customer_phone': '0240000000', 'customer_email': '',
            'delivery_area': 'pickup', 'delivery_location': '', 'landmark': '', 'delivery_notes': '',
        }
        response = self.client.post(self.checkout_url, data)
        order = Order.objects.get()
        self.assertRedirects(response, order.get_absolute_url())
        self.assertEqual(order.subtotal, Decimal('45.48'))
        self.assertEqual(order.items.get().quantity, 2)
        self.assertEqual(order.items.get().unit_price, Decimal('22.74'))
        self.assertNotIn(CART_SESSION_KEY, self.client.session)
        self.assertRedirects(self.client.post(self.checkout_url, data), order.get_absolute_url())
        self.assertEqual(Order.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock, 4)
