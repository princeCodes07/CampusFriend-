"""Offline SQLite export and guarded, transactional database import.

Bundles contain customer data, password hashes and session tokens: keep private.
No payment, email or model save workflows are invoked during deserialization.
"""

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sqlite3

from django.apps import apps
from django.core import serializers
from django.core.management.base import CommandError
from django.core.management.color import no_style
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import ConnectionHandler


SYSTEM_MODELS = {"contenttypes.contenttype", "auth.permission"}
SEED_MODEL = "repairs.phonerepairservice"
SEEDS = [
    ("Fix broken screen", "fix-broken-screen", "Display repair for cracked or non-functional phone screens.", True),
    ("Change screen", "change-screen", "Screen replacement service.", True),
    ("Fix charging system", "fix-charging-system", "Charging port and cable-related diagnostics and repair.", True),
    ("Repair speaker", "repair-speaker", "Audio speaker repair and replacement.", True),
    ("Change housing / backglass", "change-housing-backglass", "Back glass or housing replacement.", True),
    ("Special problem", "special-problem", "Custom or uncommon issue; price will be confirmed after review.", False),
]


class ExactJSONEncoder(DjangoJSONEncoder):
    def default(self, value):
        if isinstance(value, datetime):
            return value.isoformat().replace("+00:00", "Z")
        return super().default(value)


def encoded(value):
    return json.dumps(value, cls=ExactJSONEncoder, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def models_in_order():
    return serializers.sort_dependencies(
        [(app, list(app.get_models())) for app in apps.get_app_configs()], allow_cycles=True
    )


def records(using="default"):
    result = []
    for model in models_in_order():
        if not model._meta.managed or model._meta.proxy:
            continue
        rows = serializers.serialize(
            "python", model._base_manager.using(using).order_by(model._meta.pk.name),
            use_natural_foreign_keys=True,
            use_natural_primary_keys=model._meta.label_lower in SYSTEM_MODELS,
        )
        # M2M row order has no meaning and may differ between database engines.
        for row in rows:
            # Admin object_id is a generic reference. Business IDs are stable,
            # but generated metadata IDs may be remapped through natural keys.
            if row["model"] == "admin.logentry" and row["fields"].get("content_type") in {
                ("auth", "permission"), ("contenttypes", "contenttype"),
            }:
                raise CommandError("Admin history references generated metadata; a reviewed ID mapping is required.")
            for field in model._meta.local_many_to_many:
                if field.name in row["fields"]:
                    row["fields"][field.name].sort(key=encoded)
        result.extend(rows)
    return json.loads(encoded(result))


def canonical(rows):
    return sorted(encoded(row) for row in rows)


def migration_state(using):
    known_tables = {model._meta.db_table for model in apps.get_models(include_auto_created=True) if model._meta.managed and not model._meta.proxy}
    known_tables.add("django_migrations")
    if set(connections[using].introspection.table_names()) != known_tables:
        raise CommandError("Database tables differ from the application schema; investigate before transfer.")
    executor = MigrationExecutor(connections[using])
    executor.loader.check_consistent_history(connections[using])
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        raise CommandError("Pending schema migrations. Migrate a COPY of the source, or the fresh target, first.")
    return sorted([list(item) for item in executor.loader.applied_migrations])


@contextmanager
def sqlite_source(path):
    path = Path(path).resolve(strict=True)
    alias = "campusfriend_transfer_source"
    if alias in connections.databases:
        raise CommandError("Transfer source is already in use.")
    config = {"ENGINE": "django.db.backends.sqlite3", "NAME": path.as_uri() + "?mode=ro", "OPTIONS": {"uri": True}}
    connections.databases[alias] = ConnectionHandler({"default": config})["default"].settings_dict
    try:
        yield alias
    finally:
        connections[alias].close()
        del connections[alias]
        del connections.databases[alias]


def export_bundle(source, bundle):
    source = Path(source).resolve(strict=True)
    bundle = Path(bundle)
    # Exclusive creation: never replace an existing backup or fixture.
    bundle.mkdir(parents=True, exist_ok=False, mode=0o700)
    snapshot = bundle / "source.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src:
        with sqlite3.connect(snapshot) as dst:
            src.backup(dst)
            if dst.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise CommandError("SQLite integrity check failed.")
            if dst.execute("PRAGMA foreign_key_check").fetchone():
                raise CommandError("SQLite has broken foreign keys. Export stopped.")
    with sqlite_source(snapshot) as alias:
        migrations = migration_state(alias)
        data = records(alias)
    payload = encoded(data).encode("utf-8")
    (bundle / "fixture.json").write_bytes(payload)
    manifest = {
        "format": 1, "created_at": datetime.now(timezone.utc).isoformat(),
        "django": importlib.metadata.version("Django"),
        "migrations": migrations, "sha256": hashlib.sha256(payload).hexdigest(),
        "models": sorted(m._meta.label_lower for m in models_in_order()),
        "counts": {label: sum(r["model"] == label for r in data) for label in sorted({r["model"] for r in data})},
    }
    # Written last: a failed export is never a usable bundle.
    (bundle / "manifest.json").write_text(encoded(manifest), encoding="utf-8")
    return manifest


def read_bundle(bundle):
    bundle = Path(bundle)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    payload = (bundle / "fixture.json").read_bytes()
    if manifest.get("format") != 1 or hashlib.sha256(payload).hexdigest() != manifest.get("sha256"):
        raise CommandError("Bundle checksum/format mismatch; nothing imported.")
    if manifest.get("django") != importlib.metadata.version("Django"):
        raise CommandError("Use the same pinned Django version as the export.")
    if manifest.get("models") != sorted(m._meta.label_lower for m in models_in_order()):
        raise CommandError("Source and target model sets differ.")
    return manifest, json.loads(payload)


def assert_pristine(current, expected):
    """Only an empty migrated schema (plus exact built-in seeds) is acceptable."""
    source_seed_ids = {r.get("pk") for r in expected if r["model"] == SEED_MODEL}
    for row in current:
        label = row["model"]
        if label in SYSTEM_MODELS:
            # Never overwrite modified permission names or extra metadata.
            if encoded(row) not in {encoded(r) for r in expected if r["model"] == label}:
                raise CommandError("Target metadata differs from source; use a fresh matching database.")
            continue
        if label == SEED_MODEL and isinstance(row.get("pk"), int) and 1 <= row["pk"] <= len(SEEDS):
            fields = dict(row["fields"])
            fields.pop("created_at", None)
            fields.pop("updated_at", None)
            name, slug, description, priceable = SEEDS[row["pk"] - 1]
            pristine = {"name": name, "slug": slug, "description": description, "priceable": priceable, "active": True}
            if fields == pristine and row["pk"] in source_seed_ids:
                continue
        raise CommandError("Target contains existing or changed data. Import refused; use a separate fresh database.")


def verify_rows(expected, using="default"):
    if canonical(records(using)) != canonical(expected):
        raise CommandError("Full record/relationship verification failed. No customer values are logged.")


def verify_sequences(using="default"):
    connection = connections[using]
    if connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        for model in apps.get_models(include_auto_created=True):
            if model._meta.proxy or not model._meta.managed:
                continue
            table, column = model._meta.db_table, model._meta.pk.column
            cursor.execute(
                "SELECT n.nspname, c.relname FROM pg_class c "
                "JOIN pg_namespace n ON c.relnamespace = n.oid "
                "WHERE c.oid = pg_get_serial_sequence(%s, %s)::regclass", [table, column],
            )
            sequence = cursor.fetchone()
            if not sequence:
                continue
            quote = connection.ops.quote_name
            cursor.execute("SELECT last_value, is_called FROM " + ".".join(quote(part) for part in sequence))
            last, called = cursor.fetchone()
            cursor.execute(f"SELECT MAX({quote(column)}) FROM {quote(table)}")
            maximum = cursor.fetchone()[0]
            if maximum is not None and last + int(called) <= maximum:
                raise CommandError("A PostgreSQL sequence would collide with imported keys.")


def import_bundle(bundle, *, commit=False, using="default", require_postgres=True):
    connection = connections[using]
    if require_postgres and connection.vendor != "postgresql":
        raise CommandError("Import requires PostgreSQL; the local SQLite database will not be modified.")
    manifest, expected = read_bundle(bundle)
    if migration_state(using) != manifest["migrations"]:
        raise CommandError("Source and target migration histories differ.")
    with transaction.atomic(using=using):
        if connection.vendor == "postgresql":
            # Fail quickly if a web process or another import is using the target.
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                tables = sorted(connection.introspection.table_names(cursor))
                cursor.execute("LOCK TABLE " + ", ".join(connection.ops.quote_name(t) for t in tables) + " IN ACCESS EXCLUSIVE MODE")
        current = records(using)
        if canonical(current) == canonical(expected):
            return "Already matches: verified without rewriting data."
        assert_pristine(current, expected)
        deferred = []
        for obj in serializers.deserialize("python", expected, using=using, handle_forward_references=True):
            obj.save(using=using)
            if obj.deferred_fields:
                deferred.append(obj)
        for obj in deferred:
            obj.save_deferred_fields(using=using)
        connection.check_constraints()
        verify_rows(expected, using)
        if commit:
            # Includes M2M through tables. Explicit business PKs must not collide
            # with the next insert. setval is intentionally skipped on dry runs.
            models = list(apps.get_models(include_auto_created=True))
            with connection.cursor() as cursor:
                for statement in connection.ops.sequence_reset_sql(no_style(), models):
                    cursor.execute(statement)
            verify_sequences(using)
        else:
            transaction.set_rollback(True, using=using)
    return "Imported and verified." if commit else "Dry run verified; all inserted records rolled back."


def verify_bundle(bundle, using="default"):
    manifest, expected = read_bundle(bundle)
    if migration_state(using) != manifest["migrations"]:
        raise CommandError("Source and target migration histories differ.")
    verify_rows(expected, using)
    verify_sequences(using)
    return "Verified all records, keys, relationships, permissions, amounts and timestamps."
