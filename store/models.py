from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify


def _unique_slug(instance, using=None):
    """Generate a bounded slug; the database remains the uniqueness authority."""
    max_length = instance._meta.get_field("slug").max_length
    base = (slugify(instance.name) or instance._meta.model_name)[:max_length]
    base = base.rstrip("-")
    candidate = base
    number = 2
    existing = type(instance).objects.using(using or instance._state.db).exclude(
        pk=instance.pk
    )
    while existing.filter(slug=candidate).exists():
        suffix = f"-{number}"
        candidate = f"{base[:max_length - len(suffix)].rstrip('-')}{suffix}"
        number += 1
    return candidate


class Category(models.Model):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, using=kwargs.get("using"))
            if kwargs.get("update_fields"):
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"slug"}
        super().save(*args, **kwargs)


class Product(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.PROTECT, related_name="products"
    )
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    sku = models.CharField(max_length=64, unique=True, verbose_name="SKU")
    short_description = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Price in Ghana cedis (GHS).",
    )
    old_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True,
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Optional previous price in Ghana cedis (GHS).",
    )
    stock = models.PositiveIntegerField(default=0)
    image = models.ImageField(upload_to="products/%Y/%m/", blank=True)
    is_available = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gte=0),
                name="store_product_price_nonnegative",
            ),
            models.CheckConstraint(
                condition=models.Q(old_price__isnull=True) | models.Q(old_price__gte=0),
                name="store_product_old_price_nonnegative",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    @property
    def is_in_stock(self):
        """Report physical stock independently of the availability flag."""
        return self.stock > 0

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, using=kwargs.get("using"))
            if kwargs.get("update_fields"):
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"slug"}
        super().save(*args, **kwargs)
