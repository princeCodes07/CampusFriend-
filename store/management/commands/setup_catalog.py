"""Create CampusFriend's initial database-managed Store taxonomy."""

from django.core.management.base import BaseCommand
from django.db import transaction

from store.models import Category


CATALOG_STRUCTURE = (

    {
        "name": "Devices",
        "slug": "devices",
        "description": (
            "Phones, laptops and smart devices "
            "for campus life."
        ),
        "sort_order": 10,
        "show_on_homepage": False,

        "children": (

            (
                "Phones",
                "phones",
                "Phones and mobile devices.",
                10,
                True,
            ),

            (
                "Laptops",
                "laptops",
                "Laptops for study, work "
                "and everyday use.",
                20,
                True,
            ),

            (
                "Smart Devices",
                "smart-devices",
                "Smart watches and connected devices.",
                30,
                True,
            ),
        ),
    },

    {
        "name": "Accessories",
        "slug": "accessories",

        "description": (
            "Everyday accessories for phones, "
            "laptops, power and audio."
        ),

        "sort_order": 20,
        "show_on_homepage": False,

        "children": (

            (
                "Phone Accessories",
                "phone-accessories",
                (
                    "Cases, screen protection "
                    "and phone add-ons."
                ),
                10,
                True,
            ),

            (
                "Laptop Accessories",
                "laptop-accessories",
                (
                    "Laptop sleeves, mice, adapters "
                    "and useful add-ons."
                ),
                20,
                True,
            ),

            (
                "Chargers & Cables",
                "chargers-cables",
                (
                    "Chargers, cables, adapters "
                    "and connectivity essentials."
                ),
                30,
                True,
            ),

            (
                "Power Banks",
                "power-banks",
                "Portable power for long campus days.",
                40,
                True,
            ),

            (
                "Audio",
                "audio",
                (
                    "Earbuds, headphones, "
                    "headsets and speakers."
                ),
                50,
                True,
            ),

            (
                "Gaming Accessories",
                "gaming-accessories",
                (
                    "Controllers, headsets "
                    "and gaming add-ons."
                ),
                60,
                False,
            ),
        ),
    },

    {
        "name": "Campus Living",
        "slug": "campus-living",

        "description": (
            "Useful items for hostels, rooms "
            "and everyday student living."
        ),

        "sort_order": 30,
        "show_on_homepage": False,

        "children": (

            (
                "Electricals",
                "electricals",
                (
                    "Practical electrical items "
                    "for student living."
                ),
                10,
                True,
            ),

            (
                "Hostel Essentials",
                "hostel-essentials",
                (
                    "Useful everyday items "
                    "for halls and hostels."
                ),
                20,
                True,
            ),

            (
                "Gaming",
                "gaming",
                (
                    "Gaming devices and "
                    "entertainment products."
                ),
                30,
                False,
            ),
        ),
    },

    {
        "name": "Books & Study",
        "slug": "books-study",

        "description": (
            "Books, study materials and tools "
            "for learning and personal growth."
        ),

        "sort_order": 40,
        "show_on_homepage": False,

        "children": (

            (
                "Books",
                "books",
                (
                    "Personal development, finance, "
                    "productivity and other useful reads."
                ),
                10,
                True,
            ),

            (
                "Study Materials",
                "study-materials",
                (
                    "Materials and resources that "
                    "support academic work."
                ),
                20,
                True,
            ),

            (
                "Stationery",
                "stationery",
                (
                    "Notebooks, writing tools "
                    "and study essentials."
                ),
                30,
                False,
            ),
        ),
    },
)


class Command(BaseCommand):

    help = (
        "Create or organize the initial CampusFriend "
        "Store categories without creating products."
    )

    def add_arguments(
        self,
        parser,
    ):

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Show/validate the taxonomy changes "
                "and roll them back."
            ),
        )

    def handle(
        self,
        *args,
        **options,
    ):

        created = 0
        updated = 0

        with transaction.atomic():

            for section in CATALOG_STRUCTURE:

                parent, was_created = (
                    self._upsert_category(

                        name=section["name"],

                        slug=section["slug"],

                        description=(
                            section["description"]
                        ),

                        sort_order=(
                            section["sort_order"]
                        ),

                        show_on_homepage=(
                            section[
                                "show_on_homepage"
                            ]
                        ),

                        parent=None,
                    )
                )

                created += int(was_created)
                updated += int(not was_created)

                for (
                    name,
                    slug,
                    description,
                    sort_order,
                    show_on_homepage,
                ) in section["children"]:

                    _, was_created = (
                        self._upsert_category(

                            name=name,
                            slug=slug,
                            description=description,
                            sort_order=sort_order,

                            show_on_homepage=(
                                show_on_homepage
                            ),

                            parent=parent,
                        )
                    )

                    created += int(
                        was_created
                    )

                    updated += int(
                        not was_created
                    )

            if options["dry_run"]:

                transaction.set_rollback(
                    True
                )

        message = (
            f"Catalog taxonomy: "
            f"{created} created, "
            f"{updated} organized."
        )

        if options["dry_run"]:

            message += (
                " Dry run: no changes saved."
            )

        self.stdout.write(
            self.style.SUCCESS(
                message
            )
        )

    def _upsert_category(
        self,
        *,
        name,
        slug,
        description,
        sort_order,
        show_on_homepage,
        parent,
    ):

        category = (
            Category.objects
            .filter(slug=slug)
            .first()
        )

        if category is None:

            category = (
                Category.objects
                .filter(name=name)
                .first()
            )

        created = (
            category is None
        )

        if created:

            category = Category(
                name=name,
                slug=slug,
            )

        category.name = name
        category.slug = slug
        category.parent = parent

        category.description = (
            category.description.strip()
            or description
        )

        category.sort_order = (
            sort_order
        )

        category.show_on_homepage = (
            show_on_homepage
        )

        # Existing active/inactive choice
        # remains untouched.
        category.full_clean()

        category.save()

        return (
            category,
            created,
        )