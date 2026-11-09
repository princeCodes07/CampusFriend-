from decimal import Decimal
import uuid

from django.contrib.auth import SESSION_KEY, get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from orders.cart import CART_SESSION_KEY
from orders.views import GUEST_SESSION_KEY, PREVIEW_SESSION_KEY
from store.models import Category, Product


@override_settings(STORAGES={
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class AccountTests(TestCase):
     = 'Campus-test-only!River92'

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='student', =cls.)
        category = Category.objects.create(name='Accessories')
        cls.product = Product.objects.create(category=category, name='Cable', sku='ACCOUNT-CABLE', price='10.05', stock=5)

    def setUp(self):
        self.login_url = reverse('accounts:login')
        self.signup_url = reverse('accounts:signup')
        self.logout_url = reverse('accounts:logout')

    def signup_data(self, **changes):
        return {'username': 'newstudent', '1': self., '2': self., **changes}

    def fill_cart(self, client=None):
        browser = client or self.client
        browser.post(reverse('orders:cart_add', args=[self.product.pk]), {'quantity': 2})
        session = browser.session
        session[GUEST_SESSION_KEY] = str(uuid.uuid4())
        session['repair_guest_session_id'] = 'existing-guest-repair'
        session[PREVIEW_SESSION_KEY] = {'token': str(uuid.uuid4()), 'fingerprint': 'preview'}
        session.save()
        return session.session_key, session[GUEST_SESSION_KEY]

    def test_header_offers_accounts_before_cart_and_guest_checkout_stays_available(self):
        response = self.client.get(reverse('core:home'))
        content = response.content.decode()
        self.assertLess(content.index('>Sign in</a>'), content.index('>Sign up</a>'))
        self.assertLess(content.index('>Sign up</a>'), content.index('class="cart-link"'))
        self.fill_cart()
        self.assertEqual(self.client.get(reverse('orders:checkout')).status_code, 200)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_account_pages_have_post_forms_csrf_and_no_store(self):
        for url in (self.login_url, self.signup_url):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(response, 'method="post"')
                self.assertContains(response, 'name="csrfmiddlewaretoken"')
                self.assertContains(response, 'Continue shopping as a guest')
                self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_signup_hashes__logs_in_and_preserves_cart_and_guest_context(self):
        old_key, guest_id = self.fill_cart()
        response = self.client.post(self.signup_url, self.signup_data(next=reverse('orders:checkout')), follow=True)
        self.assertRedirects(response, reverse('orders:checkout'))
        user = get_user_model().objects.get(username='newstudent')
        self.assertTrue(user.check_(self.))
        self.assertNotEqual(user., self.)
        self.assertEqual(self.client.session[SESSION_KEY], str(user.pk))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session[GUEST_SESSION_KEY], guest_id)
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 2})
        self.assertEqual(response.context['cart'].subtotal, Decimal('20.10'))
        self.assertContains(response, 'Hi, newstudent')
        self.assertContains(response, 'Sign out')
        self.assertNotContains(response, '>Sign up</a>')

    def test_signup_rejects_weak_mismatched_and_duplicate_credentials(self):
        for changes in (
            {'1': '123', '2': '123'},
            {'2': 'different'},
            {'username': 'student'},
            {'username': 'STUDENT'},
            {'username': '<script>bad</script>'},
            {'username': ''},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(self.signup_url, self.signup_data(**changes))
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].errors)
                self.assertNotIn(SESSION_KEY, self.client.session)
                self.assertEqual(get_user_model().objects.count(), 1)
                self.assertNotContains(response, self.)

    def test_signup_cannot_set_privileges_or_override__validators(self):
        self.client.post(self.signup_url, self.signup_data(is_staff='true', is_superuser='true', is_active='false'))
        user = get_user_model().objects.get(username='newstudent')
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertTrue(user.is_active)

    def test_signin_preserves_cart_and_rotates_session(self):
        old_key, guest_id = self.fill_cart()
        response = self.client.post(self.login_url, {'username': 'student', '': self., 'next': reverse('orders:checkout')})
        self.assertRedirects(response, reverse('orders:checkout'))
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))
        self.assertNotEqual(self.client.session.session_key, old_key)
        self.assertEqual(self.client.session[GUEST_SESSION_KEY], guest_id)
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 2})
        self.assertEqual(self.client.session['repair_guest_session_id'], 'existing-guest-repair')

    def test_incorrect_credentials_and_inactive_accounts_are_rejected(self):
        for username,  in (('student', 'wrong'), ('missing', self.)):
            with self.subTest(username=username):
                response = self.client.post(self.login_url, {'username': username, '': })
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.context['form'].non_field_errors())
                self.assertNotIn(SESSION_KEY, self.client.session)
        self.user.is_active = False
        self.user.save(update_fields=['is_active'])
        response = self.client.post(self.login_url, {'username': 'student', '': self.})
        self.assertTrue(response.context['form'].errors)
        self.assertNotIn(SESSION_KEY, self.client.session)

    def test_authentication_posts_require_csrf(self):
        browser = Client(enforce_csrf_checks=True)
        for url, data in ((self.signup_url, self.signup_data()),
                          (self.login_url, {'username': 'student', '': self.}),
                          (self.logout_url, {})):
            with self.subTest(url=url):
                self.assertEqual(browser.post(url, data).status_code, 403)
        browser.get(self.signup_url)
        response = browser.post(self.signup_url, {**self.signup_data(), 'csrfmiddlewaretoken': browser.cookies['csrftoken'].value})
        self.assertRedirects(response, reverse('core:home'))
        self.assertEqual(browser.post(self.logout_url).status_code, 403)
        response = browser.post(self.logout_url, {'csrfmiddlewaretoken': browser.cookies['csrftoken'].value})
        self.assertRedirects(response, reverse('core:home'))
        browser.get(self.login_url)
        response = browser.post(self.login_url, {
            'username': 'newstudent', '': self.,
            'csrfmiddlewaretoken': browser.cookies['csrftoken'].value,
        })
        self.assertRedirects(response, reverse('core:home'))

    def test_auth_redirects_reject_external_urls_and_authentication_loops(self):
        for index, destination in enumerate(('https://example.test/', '//example.test/',
                                             'javascript:alert(1)', '/accounts/sign-in/',
                                             '/accounts/sign-up/', '/accounts/sign-out/')):
            for route in ('login', 'signup'):
                with self.subTest(route=route, destination=destination):
                    browser = Client()
                    data = ({'username': 'student', '': self.} if route == 'login'
                            else self.signup_data(username=f'new-{index}'))
                    response = browser.post(reverse('accounts:' + route), {**data, 'next': destination})
                    self.assertRedirects(response, reverse('core:home'))

    def test_https_authentication_cannot_redirect_to_http(self):
        for route in ('login', 'signup'):
            with self.subTest(route=route):
                browser = Client()
                data = ({'username': 'student', '': self.} if route == 'login' else self.signup_data())
                response = browser.post(reverse('accounts:' + route), {**data, 'next': 'http://testserver/shop/'}, secure=True)
                self.assertRedirects(response, reverse('core:home'))

    def test_safe_next_is_retained_when_switching_between_signin_and_signup(self):
        destination = '/shop/?q=usb&sort=price_low'
        for url in (self.login_url, self.signup_url):
            response = self.client.get(url, {'next': destination})
            self.assertEqual(response.context['next'], destination)
            self.assertContains(response, 'name="next" value="/shop/?q=usb&amp;sort=price_low"')
        response = self.client.post(self.login_url + '?next=/cart/', {
            'username': 'student', '': self., 'next': '/shop/',
        })
        self.assertRedirects(response, '/shop/')

    def test_authenticated_visitors_do_not_create_another_account_or_switch_users(self):
        self.client.force_login(self.user)
        for url, data in ((self.signup_url, self.signup_data()),
                          (self.login_url, {'username': 'different', '': self.})):
            self.assertRedirects(self.client.get(url), reverse('core:home'))
            self.assertRedirects(self.client.post(url, data), reverse('core:home'))
        self.assertEqual(get_user_model().objects.count(), 1)
        self.assertEqual(self.client.session[SESSION_KEY], str(self.user.pk))

    def test_logout_requires_post_and_preserves_only_valid_cart_quantities(self):
        self.client.force_login(self.user)
        self.fill_cart()
        for method in (self.client.get, self.client.head):
            self.assertEqual(method(self.logout_url).status_code, 405)
            self.assertIn(SESSION_KEY, self.client.session)
        Product.objects.filter(pk=self.product.pk).update(stock=1)
        response = self.client.post(self.logout_url)
        self.assertRedirects(response, reverse('core:home'))
        self.assertEqual(self.client.session[CART_SESSION_KEY], {str(self.product.pk): 1})
        for key in (SESSION_KEY, GUEST_SESSION_KEY, PREVIEW_SESSION_KEY, 'repair_guest_session_id'):
            self.assertNotIn(key, self.client.session)

    def test_signout_is_safe_for_an_empty_anonymous_session(self):
        response = self.client.post(self.logout_url)
        self.assertRedirects(response, reverse('core:home'))
        self.assertNotIn(CART_SESSION_KEY, self.client.session)
        self.assertNotIn(SESSION_KEY, self.client.session)
