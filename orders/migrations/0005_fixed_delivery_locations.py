from decimal import Decimal

import django.core.validators
from django.db import migrations, models


def preserve_location_names(apps, schema_editor):
    Order = apps.get_model("orders", "Order")
    alias = schema_editor.connection.alias
    for order in Order.objects.using(alias).filter(delivery_area_name="", delivery_zone__isnull=False).select_related("delivery_zone").iterator():
        Order.objects.using(alias).filter(pk=order.pk).update(delivery_area_name=order.delivery_zone.name)


class Migration(migrations.Migration):
    dependencies = [("orders", "0004_delivery_pricing_v1")]

    operations = [
        migrations.AddField(
            model_name="order", name="delivery_area",
            field=models.CharField(blank=True, default="", max_length=20, choices=[
                ("campus", "Campus"), ("pickup", "Pickup (Palms Eatery)"),
                ("ayeduase", "Ayeduase"), ("kotei", "Kotei"), ("boadi", "Boadi"),
                ("newsite", "Newsite"), ("other", "Other location"),
            ]),
        ),
        migrations.RenameField(model_name="order", old_name="delivery_zone_name", new_name="delivery_area_name"),
        migrations.AlterField(
            model_name="order", name="delivery_area_name",
            field=models.CharField(blank=True, editable=False, max_length=150, verbose_name="Selected location"),
        ),
        migrations.AlterField(
            model_name="order", name="delivery_fee",
            field=models.DecimalField(blank=True, null=True, max_digits=10, decimal_places=2,
                validators=[django.core.validators.MinValueValidator(Decimal("0.00"))],
                help_text="Delivery included in the online total. For Other location, delivery is agreed and paid separately. Blank denotes a legacy pending quote."),
        ),
        migrations.RunPython(preserve_location_names, migrations.RunPython.noop),
        migrations.RemoveField(model_name="order", name="delivery_zone"),
        migrations.DeleteModel(name="DeliveryZone"),
    ]
