from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        (
            "store",
            "0003_require_valid_previous_price",
        ),
    ]

    operations = [

        migrations.AddField(
            model_name="category",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                help_text=(
                    "Optional parent Store section. "
                    "Leave blank for a top-level category."
                ),
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="children",
                to="store.category",
            ),
        ),

        migrations.AddField(
            model_name="category",
            name="show_on_homepage",
            field=models.BooleanField(
                default=True,
                help_text=(
                    "Eligible populated categories may "
                    "appear in homepage category discovery."
                ),
            ),
        ),

        migrations.AddField(
            model_name="category",
            name="sort_order",
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text=(
                    "Lower numbers appear first "
                    "in Store category navigation."
                ),
            ),
        ),

        migrations.AlterModelOptions(
            name="category",
            options={
                "ordering": [
                    "sort_order",
                    "name",
                    "pk",
                ],
                "verbose_name_plural":
                "categories",
            },
        ),
    ]