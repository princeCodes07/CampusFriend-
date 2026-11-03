"""A guest cart: store quantities in the session, read prices from the catalog."""

from decimal import Decimal

from django.contrib import messages

from store.catalog import visible_products


CART_SESSION_KEY = "cart"


def valid_quantities(saved):
    quantities = {}
    if isinstance(saved, dict):
        for key, quantity in saved.items():
            if (
                isinstance(key, str) and key.isascii() and key.isdecimal()
                and len(key) <= 19 and 0 < int(key) <= 9223372036854775807
                and str(int(key)) == key and type(quantity) is int and quantity > 0
            ):
                quantities[key] = quantity
    return quantities


class Cart:
    def __init__(self, session):
        self.session = session
        saved = session.get(CART_SESSION_KEY, {})
        quantities = valid_quantities(saved)

        self.products = {
            str(product.pk): product
            for product in visible_products().filter(pk__in=quantities, stock__gt=0)
        } if quantities else {}
        self.quantities = {
            key: min(quantity, self.products[key].stock)
            for key, quantity in quantities.items()
            if key in self.products
        }
        self.adjusted = self.quantities != saved
        if self.adjusted:
            self._save()

    def _save(self):
        if self.quantities:
            self.session[CART_SESSION_KEY] = self.quantities.copy()
        else:
            self.session.pop(CART_SESSION_KEY, None)

    def add(self, product, quantity):
        if not product.is_in_stock:
            raise ValueError("This product is currently unavailable to add to your cart.")
        key = str(product.pk)
        total_quantity = self.quantities.get(key, 0) + quantity
        if total_quantity > product.stock:
            raise ValueError(
                f"Only {product.stock} available. You already have "
                f"{self.quantities.get(key, 0)} in your cart."
            )
        self.quantities[key] = total_quantity
        self.products[key] = product
        self._save()

    def remove(self, product_id):
        key = str(product_id)
        removed = self.quantities.pop(key, None) is not None
        self.products.pop(key, None)
        self._save()
        return removed

    @property
    def count(self):
        return sum(self.quantities.values())

    @property
    def items(self):
        return [
            {
                "product": self.products[key],
                "quantity": quantity,
                "line_total": self.products[key].price * quantity,
            }
            for key, quantity in self.quantities.items()
        ]

    @property
    def subtotal(self):
        return sum((item["line_total"] for item in self.items), Decimal("0.00"))


def get_cart(request):
    if not hasattr(request, "_campus_cart"):
        request._campus_cart = Cart(request.session)
        if request._campus_cart.adjusted:
            messages.info(request, "Your cart was updated to match current stock and availability.")
    return request._campus_cart
