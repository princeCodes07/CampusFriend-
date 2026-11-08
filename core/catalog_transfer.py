"""Reviewed catalog-only transfer. Never updates or deletes existing rows."""

import hashlib
import json
from pathlib import Path
import sqlite3

import django
from django.apps import apps
from django.core import serializers
from django.core.management.base import CommandError
from django.db import connections, transaction

from core.db_transfer import canonical, encoded, migration_state, sqlite_source, verify_sequences

LABELS = ("store.category", "store.product", "core.businesscontact")
MAX_BYTES = 2 * 1024 * 1024


def require(condition, code):
    if not condition:
        raise CommandError(code)


def selected_rows(using, label, pks=None):
    query = apps.get_model(label)._base_manager.using(using).order_by("pk")
    if pks is not None:
        query = query.filter(pk__in=pks)
    return json.loads(encoded(serializers.serialize("python", query)))


def table_counts(using):
    return {model._meta.label_lower: model._base_manager.using(using).count()
            for model in apps.get_models() if model._meta.managed and not model._meta.proxy}


def validate_rows(rows):
    require(isinstance(rows, list), "INVALID_ROWS")
    seen = set()
    for row in rows:
        require(isinstance(row, dict) and set(row) == {"model", "pk", "fields"}, "INVALID_RECORD")
        require(row["model"] in LABELS, "OUT_OF_SCOPE_MODEL_REFUSED")
        pk = row["pk"]
        require(type(pk) is int and 0 < pk < 2**63, "INVALID_PRIMARY_KEY")
        key = row["model"], pk
        require(key not in seen, "DUPLICATE_PRIMARY_KEY")
        seen.add(key)
        model = apps.get_model(row["model"])
        fields = {f.name for f in model._meta.local_fields if f.serialize and not f.primary_key}
        require(isinstance(row["fields"], dict) and set(row["fields"]) == fields, "FIELD_SET_MISMATCH")
    categories = {r["pk"]: r for r in rows if r["model"] == "store.category"}
    for pk, row in categories.items():
        parent = row["fields"]["parent"]
        require(parent is None or type(parent) is int, "INVALID_PARENT_KEY")
        visited = {pk}
        while parent is not None:
            require(parent in categories and parent not in visited, "MISSING_PARENT_OR_CATEGORY_CYCLE")
            visited.add(parent)
            parent = categories[parent]["fields"]["parent"]
    for row in rows:
        if row["model"] == "store.product":
            require(type(row["fields"]["category"]) is int and row["fields"]["category"] in categories,
                    "PRODUCT_CATEGORY_MISSING")
    require(sum(r["model"] == "core.businesscontact" for r in rows) <= 1, "MULTIPLE_SOURCE_CONTACTS")


def ordered_rows(rows):
    pending = {r["pk"]: r for r in rows if r["model"] == "store.category"}
    done = set()
    ordered = []
    while pending:
        ready = [pk for pk, row in pending.items() if row["fields"]["parent"] is None or row["fields"]["parent"] in done]
        require(bool(ready), "CATEGORY_ORDER_FAILED")
        for pk in sorted(ready):
            ordered.append(pending.pop(pk))
            done.add(pk)
    for label in LABELS[1:]:
        ordered.extend(sorted((r for r in rows if r["model"] == label), key=lambda r: r["pk"]))
    return ordered


def export_catalog(source, bundle_dir, review):
    """Create a private snapshot and catalog payload; do not write the source."""
    require(set(review) >= {"reviewed", "excluded_product_ids", "excluded_category_ids"}, "INVALID_REVIEW")
    require(type(review["reviewed"]) is bool, "INVALID_REVIEW")
    source = Path(source).resolve(strict=True)
    bundle = Path(bundle_dir)
    bundle.mkdir(parents=True, exist_ok=False, mode=0o700)
    snapshot = bundle / "source.sqlite3"
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True) as src, sqlite3.connect(snapshot) as dst:
        src.backup(dst)
        require(dst.execute("PRAGMA integrity_check").fetchall() == [("ok",)], "SOURCE_INTEGRITY_FAILED")
        require(dst.execute("PRAGMA foreign_key_check").fetchone() is None, "SOURCE_FOREIGN_KEYS_FAILED")
    with sqlite_source(snapshot) as alias:
        migrations = migration_state(alias)
        rows = [row for label in LABELS for row in selected_rows(alias, label)]
    for label, key in [("store.product", "excluded_product_ids"), ("store.category", "excluded_category_ids")]:
        excluded = review[key]
        require(isinstance(excluded, list) and all(type(pk) is int for pk in excluded), "INVALID_EXCLUSION_IDS")
        require(len(set(excluded)) == len(excluded), "DUPLICATE_EXCLUSION_IDS")
        require(set(excluded) <= {r["pk"] for r in rows if r["model"] == label}, "UNKNOWN_EXCLUSION_ID")
        rows = [r for r in rows if not (r["model"] == label and r["pk"] in excluded)]
    validate_rows(rows)
    document = {"format": "campusfriend-catalog-v1", "django": django.get_version(),
                "source_snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                "migrations": migrations, "review": review, "rows": ordered_rows(rows)}
    payload = encoded(document).encode("utf-8")
    require(len(payload) <= MAX_BYTES, "BUNDLE_TOO_LARGE")
    (bundle / "catalog.json").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (bundle / "sha256.txt").write_text(digest + "\n", encoding="ascii")
    return digest, {label: sum(r["model"] == label for r in rows) for label in LABELS}


def load_catalog(payload, expected_sha256):
    require(len(payload) <= MAX_BYTES, "BUNDLE_TOO_LARGE")
    require(len(expected_sha256) == 64 and hashlib.sha256(payload).hexdigest() == expected_sha256, "BUNDLE_CHECKSUM_MISMATCH")
    document = json.loads(payload)
    require(document.get("format") == "campusfriend-catalog-v1", "INVALID_BUNDLE_FORMAT")
    require(document.get("django") == django.get_version(), "DJANGO_VERSION_MISMATCH")
    validate_rows(document["rows"])
    return document


def preflight(document, using):
    require(migration_state(using) == document["migrations"], "MIGRATION_HISTORY_MISMATCH")
    new = []
    matches = {label: 0 for label in LABELS}
    incoming = document["rows"]
    for label in LABELS:
        model = apps.get_model(label)
        current = selected_rows(using, label)
        require(label != "core.businesscontact" or len(current) <= 1 or not any(r["model"] == label for r in incoming),
                "MULTIPLE_EXISTING_BUSINESS_CONTACTS")
        by_pk = {row["pk"]: row for row in current}
        unique_fields = [field.name for field in model._meta.fields if field.unique and not field.primary_key]
        for row in [r for r in incoming if r["model"] == label]:
            if row["pk"] in by_pk:
                require(canonical([row]) == canonical([by_pk[row["pk"]]]), "EXISTING_PRIMARY_KEY_DIFFERS")
                matches[label] += 1
                continue
            for field in unique_fields:
                require(not any(existing["fields"][field] == row["fields"][field] for existing in current),
                        "EXISTING_UNIQUE_VALUE_COLLISION")
            # The footer reads the first contact; don't silently introduce a second.
            require(label != "core.businesscontact" or not current, "EXISTING_BUSINESS_CONTACT_CONFLICT")
            new.append(row)
    counts = table_counts(using)
    inserts = {label: sum(row["model"] == label for row in new) for label in LABELS}
    return new, {"before_counts": counts, "insert_counts": inserts, "identical_counts": matches,
                 "expected_after_counts": {label: count + inserts.get(label, 0) for label, count in counts.items()}}


def verify_selected(document, using):
    for label in LABELS:
        expected = [r for r in document["rows"] if r["model"] == label]
        actual = selected_rows(using, label, [r["pk"] for r in expected])
        require(canonical(actual) == canonical(expected), "SELECTED_RECORD_VERIFICATION_FAILED")


def advance_sequences(connection):
    """Advance only: never move a production sequence backwards."""
    if connection.vendor != "postgresql":
        return
    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for label in LABELS:
            model = apps.get_model(label)
            table, column = model._meta.db_table, model._meta.pk.column
            cursor.execute("SELECT n.nspname,c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
                           "WHERE c.oid=pg_get_serial_sequence(%s,%s)::regclass", [table, column])
            sequence = cursor.fetchone()
            require(sequence is not None, "EXPECTED_SEQUENCE_MISSING")
            sequence_name = '.'.join(quote(part) for part in sequence)
            cursor.execute("SELECT last_value FROM " + sequence_name)
            last = cursor.fetchone()[0]
            cursor.execute(f"SELECT COALESCE(MAX({quote(column)}),0) FROM {quote(table)}")
            maximum = cursor.fetchone()[0]
            cursor.execute("SELECT setval(%s::regclass,%s,true)", [sequence_name, max(last, maximum, 1)])


def transfer(document, *, mode="check", using="default", allow_sqlite_tests=False):
    require(mode in {"check", "dry-run", "commit", "verify"}, "INVALID_MODE")
    connection = connections[using]
    require(connection.vendor == "postgresql" or allow_sqlite_tests, "POSTGRESQL_REQUIRED")
    validate_rows(document["rows"])
    if mode in {"dry-run", "commit"}:
        require(document["review"].get("reviewed") is True, "SELECTION_REVIEW_REQUIRED")
    with transaction.atomic(using=using):
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                if mode in {"check", "verify"}:
                    cursor.execute("SET TRANSACTION READ ONLY")
                cursor.execute("SELECT set_config('lock_timeout','5000',true)")
                cursor.execute("SELECT set_config('statement_timeout','60000',true)")
                if mode in {"dry-run", "commit"}:
                    tables = sorted(apps.get_model(label)._meta.db_table for label in LABELS)
                    cursor.execute("LOCK TABLE " + ','.join(connection.ops.quote_name(t) for t in tables) + " IN ACCESS EXCLUSIVE MODE")
        new, receipt = preflight(document, using)
        if mode == "check":
            return {"result": "PREFLIGHT_ONLY_NO_WRITES", **receipt}
        if mode == "verify":
            verify_selected(document, using)
            verify_sequences(using)
            return {"result": "VERIFIED_NO_WRITES", **receipt}
        for row in ordered_rows(document["rows"]):
            if row not in new:
                continue
            obj = next(serializers.deserialize("python", [row], using=using))
            # force_insert makes overwriting existing PKs impossible. raw retains
            # source timestamps and bypasses slug/auto_now/save workflows.
            obj.object.save_base(raw=True, force_insert=True, using=using)
        connection.check_constraints()
        verify_selected(document, using)
        require(table_counts(using) == receipt["expected_after_counts"], "ROW_COUNT_VERIFICATION_FAILED")
        receipt["inserted_ids"] = {label: [r["pk"] for r in new if r["model"] == label] for label in LABELS}
        if mode == "commit" and new:
            advance_sequences(connection)
        elif mode == "dry-run":
            transaction.set_rollback(True, using=using)
        if mode == "commit":
            verify_sequences(using)
        receipt["result"] = "DRY_RUN_ROLLED_BACK" if mode == "dry-run" else ("COMMITTED" if new else "ALREADY_IDENTICAL_NO_CHANGES")
    return receipt
