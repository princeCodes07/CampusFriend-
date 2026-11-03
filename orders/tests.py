from decimal import Decimal

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from store.models import Category, Product

from .cart import CART_SESSION_KEY


@override_settings(STORAGES={
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class CartTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Accessories")
        cls.frame = Product.objects.create(
            category=cls.category, name="Frame", sku="FRAME-TEST",
            price=Decimal("22.74"), stock=4,
        )
        cls.cable = Product.objects.create(
            category=cls.category, name="Cable", sku="CABLE-TEST",
            price=Decimal("10.05"), stock=20,
        )

    def setUp(self):
        self.cart_url = reverse("orders:cart_detail")
        self.add_url = reverse("orders:cart_add", args=[self.frame.pk])
        self.remove_url = reverse("orders:cart_remove", args=[self.frame.pk])

    def add(self, quantity=1, product=None, **extra):
        url = reverse("orders:cart_add", args=[(product or self.frame).pk])
        return self.client.post(url, {"quantity": quantity, **extra}, follow=True)

    def test_empty_cart_shows_zero_and_shop_link_without_creating_a_session(self):
        response = self.client.get(self.cart_url)
        self.assertContains(response, "Your cart is empty")
        self.assertContains(response, 'aria-label="Cart, 0 items"')
        self.assertContains(response, f'href="{reverse("store:product_list")}"')
        self.assertNotIn(settings.SESSION_COOKIE_NAME, response.cookies)

    def test_add_redirects_to_cart_and_displays_quantity_and_decimal_totals(self):
        response = self.add(2)
        self.assertRedirects(response, self.cart_url)
        self.assertContains(response, "Added 2 × Frame to your cart.")
        self.assertContains(response, "GH₵ 45.48")
        self.assertContains(response, "Quantity: 2")
        self.assertContains(response, 'aria-label="Cart, 2 items"')
        self.assertEqual(response.context["cart"].subtotal, Decimal("45.48"))
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.frame.pk): 2})

    def test_repeat_add_merges_line_and_badge_counts_units_across_products(self):
        self.add()
        self.add()
        response = self.add(3, self.cable)
        self.assertEqual(len(response.context["cart"].items), 2)
        self.assertContains(response, 'aria-label="Cart, 5 items"')
        self.assertEqual(response.context["cart"].subtotal, Decimal("75.63"))

    def test_count_persists_on_other_pages_and_refresh_does_not_add_again(self):
        self.add(2)
        for url in (self.cart_url, reverse("core:home"), reverse("store:product_list"),
                    self.frame.get_absolute_url(), reverse("orders:order_list")):
            with self.subTest(url=url):
                self.assertContains(self.client.get(url), 'aria-label="Cart, 2 items"')
        self.assertEqual(self.client.session[CART_SESSION_KEY][str(self.frame.pk)], 2)

    def test_carts_are_isolated_between_visitors(self):
        self.add(2)
        other = Client()
        self.assertContains(other.get(self.cart_url), "Your cart is empty")
        response = other.post(self.add_url, {"quantity": 1}, follow=True)
        self.assertContains(response, 'aria-label="Cart, 1 item"')
        self.assertContains(self.client.get(self.cart_url), 'aria-label="Cart, 2 items"')

    def test_prices_and_totals_cannot_be_overridden_by_post_data(self):
        response = self.add(2, price="0.01", subtotal="0.02", stock=100)
        self.assertEqual(response.context["cart"].subtotal, Decimal("45.48"))
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.frame.pk): 2})

    def test_cart_uses_updated_catalog_prices(self):
        self.add(2)
        Product.objects.filter(pk=self.frame.pk).update(price=Decimal("25.10"))
        response = self.client.get(self.cart_url)
        self.assertContains(response, "GH₵ 50.20")
        self.assertEqual(response.context["cart"].subtotal, Decimal("50.20"))

    def test_invalid_quantities_leave_existing_cart_unchanged(self):
        self.add()
        for quantity in ("", "0", "-1", "1.5", "abc", "NaN", "Infinity", "2147483648"):
            with self.subTest(quantity=quantity):
                response = self.add(quantity)
                self.assertRedirects(response, self.frame.get_absolute_url())
                self.assertContains(response, 'class="message error"')
                self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.frame.pk): 1})

    def test_missing_quantity_is_rejected(self):
        response = self.client.post(self.add_url, {}, follow=True)
        self.assertContains(response, "Choose a quantity to add.")
        self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_quantity_cannot_exceed_current_stock(self):
        response = self.add(5, stock=100)
        self.assertContains(response, "Only 4 available.")
        self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_repeated_add_cannot_exceed_stock(self):
        self.add(3)
        response = self.add(2)
        self.assertContains(response, "You already have 3 in your cart.")
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.frame.pk): 3})
        self.assertContains(self.add(1), 'aria-label="Cart, 4 items"')

    def test_unknown_or_zero_stock_cannot_be_added_even_with_direct_post(self):
        for stock in (None, 0):
            with self.subTest(stock=stock):
                Product.objects.filter(pk=self.frame.pk).update(stock=stock)
                response = self.add()
                self.assertContains(response, "This product is currently unavailable")
                self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_hidden_product_or_category_cannot_be_added(self):
        Product.objects.filter(pk=self.frame.pk).update(is_available=False)
        self.assertEqual(self.client.post(self.add_url, {"quantity": 1}).status_code, 404)
        Product.objects.filter(pk=self.frame.pk).update(is_available=True)
        Category.objects.filter(pk=self.category.pk).update(is_active=False)
        self.assertEqual(self.client.post(self.add_url, {"quantity": 1}).status_code, 404)
        self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_nonexistent_product_returns_404(self):
        url = reverse("orders:cart_add", args=[999999])
        self.assertEqual(self.client.post(url, {"quantity": 1}).status_code, 404)

    def test_cart_mutations_require_post(self):
        for url in (self.add_url, self.remove_url):
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)
                self.assertEqual(self.client.head(url).status_code, 405)
        self.assertEqual(self.client.post(self.cart_url).status_code, 405)

    def test_cart_mutations_require_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        self.assertEqual(browser.post(self.add_url, {"quantity": 1}).status_code, 403)
        browser.get(self.frame.get_absolute_url())
        token = browser.cookies["csrftoken"].value
        response = browser.post(self.add_url, {"quantity": 1, "csrfmiddlewaretoken": token})
        self.assertRedirects(response, self.cart_url)
        self.assertEqual(browser.post(self.remove_url).status_code, 403)
        self.assertEqual(browser.session[CART_SESSION_KEY][str(self.frame.pk)], 1)
        browser.post(self.remove_url, {"csrfmiddlewaretoken": token})
        self.assertNotIn(CART_SESSION_KEY, browser.session)

    def test_remove_updates_count_subtotal_and_keeps_other_products(self):
        self.add(2)
        self.add(3, self.cable)
        response = self.client.post(self.remove_url, follow=True)
        self.assertContains(response, "Item removed from your cart.")
        self.assertContains(response, 'aria-label="Cart, 3 items"')
        self.assertEqual(response.context["cart"].subtotal, Decimal("30.15"))
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.cable.pk): 3})

    def test_removing_last_item_returns_empty_state_and_can_be_repeated(self):
        self.add()
        for _ in range(2):
            response = self.client.post(self.remove_url, follow=True)
            self.assertContains(response, "Your cart is empty")
            self.assertContains(response, 'aria-label="Cart, 0 items"')
            self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_add_and_remove_do_not_reduce_stock(self):
        self.add(4)
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.stock, 4)
        self.client.post(self.remove_url)
        self.frame.refresh_from_db()
        self.assertEqual(self.frame.stock, 4)

    def test_reduced_stock_adjusts_saved_cart_and_explains_change(self):
        self.add(4)
        Product.objects.filter(pk=self.frame.pk).update(stock=2)
        response = self.client.get(self.cart_url)
        self.assertContains(response, "Your cart was updated to match current stock and availability.")
        self.assertContains(response, 'aria-label="Cart, 2 items"')
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.frame.pk): 2})

    def test_products_that_become_unavailable_are_removed_from_saved_cart(self):
        for changes in ({"stock": 0}, {"stock": None}, {"is_available": False}):
            with self.subTest(changes=changes):
                Product.objects.filter(pk=self.frame.pk).update(stock=4, is_available=True)
                self.add()
                Product.objects.filter(pk=self.frame.pk).update(**changes)
                response = self.client.get(self.cart_url)
                self.assertContains(response, "Your cart is empty")
                self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_deactivated_category_is_removed_from_saved_cart(self):
        self.add()
        Category.objects.filter(pk=self.category.pk).update(is_active=False)
        self.assertContains(self.client.get(self.cart_url), "Your cart is empty")

    def test_deleted_product_is_removed_from_saved_cart(self):
        self.add()
        self.frame.delete()
        self.assertContains(self.client.get(self.cart_url), "Your cart is empty")

    def test_malformed_session_is_discarded_without_breaking_cart(self):
        for saved in (None, [], "bad", {"no-id": 2}, {"9" * 20: 1},
                      {str(self.frame.pk): "2"}, {str(self.frame.pk): -1},
                      {str(self.frame.pk): True}):
            with self.subTest(saved=saved):
                session = self.client.session
                session[CART_SESSION_KEY] = saved
                session.save()
                self.assertContains(self.client.get(self.cart_url), "Your cart is empty")
                self.assertNotIn(CART_SESSION_KEY, self.client.session)

    def test_shop_card_and_detail_both_offer_working_cart_forms(self):
        for url in (reverse("store:product_list"), self.frame.get_absolute_url()):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, f'action="{self.add_url}"')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertContains(response, "Add to cart")
