from .cart import get_cart


def cart_count(request):
    return {"cart_count": get_cart(request).count}
