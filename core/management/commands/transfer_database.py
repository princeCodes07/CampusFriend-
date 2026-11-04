from django.core.management.base import BaseCommand, CommandError

from core.db_transfer import export_bundle, import_bundle, verify_bundle


class Command(BaseCommand):
    help = "Export a private SQLite snapshot; dry-run/import or verify a fresh PostgreSQL target."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["export", "import", "verify"])
        parser.add_argument("--bundle", required=True, help="Private local directory, never source control.")
        parser.add_argument("--source", help="SQLite source path (export only); opened read-only.")
        parser.add_argument("--commit", action="store_true", help="Import only: persist after verification. Default rolls back.")

    def handle(self, *args, **options):
        action = options["action"]
        if options["commit"] and action != "import":
            raise CommandError("--commit is only valid for import.")
        if bool(options["source"]) != (action == "export"):
            raise CommandError("--source is required for export and forbidden for import/verify.")
        try:
            if action == "export":
                manifest = export_bundle(options["source"], options["bundle"])
                result = f"Private snapshot exported: {sum(manifest['counts'].values())} records. Protect the entire bundle."
            elif action == "import":
                result = import_bundle(options["bundle"], commit=options["commit"])
            else:
                result = verify_bundle(options["bundle"])
        except CommandError:
            raise
        except Exception as error:
            # Database/deserializer error text can contain URLs or customer data.
            raise CommandError(f"Transfer failed ({type(error).__name__}). Check private configuration, schema and bundle; no data values are logged.") from None
        self.stdout.write(self.style.SUCCESS(result))
