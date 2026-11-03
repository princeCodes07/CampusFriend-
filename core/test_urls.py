"""Public routes must resolve to the same app and name used to build their URL."""
from types import ModuleType

from django.test import SimpleTestCase
from django.urls import NoReverseMatch, URLResolver, get_resolver, resolve, reverse


class PublicURLTests(SimpleTestCase):
    def test_named_public_routes_are_not_shadowed_by_other_apps(self):
        resolver = get_resolver()
        reordered = ModuleType("reordered_public_routes")
        reordered.urlpatterns = list(reversed(resolver.url_patterns))
        for app in resolver.url_patterns:
            if not isinstance(app, URLResolver) or app.namespace not in {"core", "orders", "repairs", "store", "accounts"}:
                continue
            for route in app.url_patterns:
                name = f"{app.namespace}:{route.name}"
                values = {key: 1 if key == "product_id" else "route-check" for key in route.pattern.converters}
                url = reverse(name, kwargs=values)
                for urlconf in (None, reordered):
                    with self.subTest(name=name, reordered=urlconf is not None):
                        self.assertEqual(resolve(url, urlconf=urlconf).view_name, name)

    def test_domain_destinations_have_one_canonical_owner(self):
        for url, name in (("/repairs/", "repairs:home"), ("/track/", "orders:track"),
                          ("/orders/", "orders:order_list"), ("/books/", "store:books")):
            with self.subTest(url=url):
                self.assertEqual(reverse(name), url)
                self.assertEqual(resolve(url).view_name, name)
        for obsolete in ("core:repairs", "core:track"):
            with self.subTest(name=obsolete), self.assertRaises(NoReverseMatch):
                reverse(obsolete)
