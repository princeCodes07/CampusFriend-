from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.text import slugify
from django.urls import reverse


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
    """
    Database-managed Store taxonomy.

    Top-level categories act as Store sections, for example:
        Accessories
        Devices
        Campus Living
        Books & Study

    Child categories contain the more specific product groups:
        Audio
        Power Banks
        Phone Accessories
        Laptops
        Books
    """

    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
        help_text=(
            "Optional parent Store section. "
            "Leave blank for a top-level category."
        ),
    )

    name = models.CharField(
        max_length=120,
        unique=True,
    )

    slug = models.SlugField(
        max_length=140,
        unique=True,
        blank=True,
    )

    description = models.TextField(
        blank=True,
    )

    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Lower numbers appear first in Store category navigation.",
    )

    show_on_homepage = models.BooleanField(
        default=True,
        help_text=(
            "Eligible populated categories may appear "
            "in homepage category discovery."
        ),
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        ordering = [
            "sort_order",
            "name",
            "pk",
        ]

        verbose_name_plural = "categories"

    def __str__(self):
        if self.parent_id:
            return f"{self.parent.name} → {self.name}"

        return self.name

    def get_absolute_url(self):
        return reverse(
            "store:category",
            args=[self.slug],
        )

    def clean(self):
        super().clean()

        if not self.parent_id:
            return

        if self.pk and self.parent_id == self.pk:
            raise ValidationError(
                {
                    "parent":
                    "A category cannot be its own parent."
                }
            )

        # Prevent circular category structures such as:
        #
        # Accessories
        #   -> Audio
        #      -> Accessories
        #
        ancestor = self.parent

        visited = (
            {self.pk}
            if self.pk
            else set()
        )

        while ancestor is not None:

            if ancestor.pk in visited:
                raise ValidationError(
                    {
                        "parent":
                        "Category hierarchy cannot contain a cycle."
                    }
                )

            visited.add(
                ancestor.pk
            )

            ancestor = ancestor.parent

    def save(self, *args, **kwargs):

        if not self.slug:

            self.slug = _unique_slug(
                self,
                using=kwargs.get("using"),
            )

            if kwargs.get("update_fields"):

                kwargs["update_fields"] = (
                    set(kwargs["update_fields"])
                    | {"slug"}
                )

        super().save(
            *args,
            **kwargs,
        )


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
        help_text="Optional previous price in GHS. Must be higher than the current price.",
    )
    stock = models.PositiveIntegerField(
        null=True, blank=True, default=None,
        help_text="Leave blank until quantity is confirmed. Use 0 only when out of stock.",
    )
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
            models.CheckConstraint(
                condition=models.Q(old_price__isnull=True) | models.Q(old_price__gt=models.F("price")),
                name="store_product_old_price_above_price",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def get_absolute_url(self):
        return reverse("store:product_detail", args=[self.slug])

    def clean(self):
        super().clean()
        # full_clean also calls this when field validation has reported errors.
        try:
            stock = self._meta.get_field("stock").to_python(self.stock)
        except ValidationError:
            pass
        else:
            if self.is_featured and (stock is None or stock <= 0):
                raise ValidationError({
                    "is_featured": "Only products with confirmed stock above zero can be featured."
                })
        # Let those field errors handle malformed or non-finite decimal values.
        try:
            price = self._meta.get_field("price").to_python(self.price)
            old_price = self._meta.get_field("old_price").to_python(self.old_price)
        except ValidationError:
            return
        if price is not None and old_price is not None and old_price <= price:
            raise ValidationError({"old_price": "Previous price must be higher than the current price."})

    @property
    def is_demo(self):
        return self.sku.startswith("DEMO-")

    @property
    def is_in_stock(self):
        """Report physical stock independently of the availability flag."""
        return self.stock is not None and self.stock > 0

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = _unique_slug(self, using=kwargs.get("using"))
            if kwargs.get("update_fields"):
                kwargs["update_fields"] = set(kwargs["update_fields"]) | {"slug"}
        super().save(*args, **kwargs)
