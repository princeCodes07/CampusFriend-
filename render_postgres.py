"""One-time, empty-target PostgreSQL bootstrap. Default: read-only inspection.

Credentials and expected target identifiers belong only in Render environment
settings. This entry point does not open SQLite or import any source records.
"""

import argparse
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys

from config.safe_logging import exception_summary

ROOT = Path(__file__).resolve().parent
LOCK_ID = 72640091162026


class Refused(Exception):
    """Only fixed, credential-free reason codes are used with this exception."""


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def emit(message):
    print(message, flush=True)


def validate_target(connection, settings, environ):
    require(
        environ.get("RENDER", "").strip().lower() == "true",
        "NOT_RENDER",
    )
    require(not settings.DEBUG, "DEBUG_MUST_BE_FALSE")
    require(
        bool(environ.get("DATABASE_URL", "").strip()),
        "DATABASE_URL_REQUIRED",
    )
    require(
        connection.vendor == "postgresql",
        "POSTGRESQL_REQUIRED_SQLITE_REFUSED",
    )

    config = connection.settings_dict
    expected_host = environ.get("EXPECTED_DB_HOST", "").strip()
    expected_name = environ.get("EXPECTED_DB_NAME", "").strip()

    require(
        bool(expected_host and expected_name),
        "EXPECTED_TARGET_REQUIRED",
    )
    require(
        config["HOST"] == expected_host and config["NAME"] == expected_name,
        "TARGET_MISMATCH",
    )
    require(
        config.get("OPTIONS", {}).get("sslmode")
        in {"require", "verify-ca", "verify-full"},
        "TLS_REQUIRED",
    )


def verify_server(connection):
    require(connection.connection.pgconn.ssl_in_use, "TLS_NOT_ACTIVE")

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT current_database(), current_user, "
            "current_schema(), pg_is_in_recovery()"
        )
        name, user, schema, standby = cursor.fetchone()

    require(
        name == connection.settings_dict["NAME"],
        "CONNECTED_DATABASE_MISMATCH",
    )
    require(
        user == connection.settings_dict["USER"],
        "CONNECTED_ROLE_MISMATCH",
    )
    require(schema == "public", "PUBLIC_SCHEMA_REQUIRED")
    require(not standby, "PRIMARY_DATABASE_REQUIRED")

    emit("target_verified=true tls_active=true backend=postgresql")


def reviewed_graph(loader):
    import django

    manifest = json.loads(
        (ROOT / "render_migration_manifest.json").read_text(encoding="utf-8")
    )
    require(
        django.get_version() == manifest["django_version"],
        "DJANGO_VERSION_CHANGED_REVIEW_REQUIRED",
    )

    actual = {}
    for (app, name), migration in loader.disk_migrations.items():
        module = importlib.import_module(type(migration).__module__)
        data = Path(module.__file__).read_bytes().replace(b"\r\n", b"\n")
        actual[f"{app}.{name}"] = hashlib.sha256(data).hexdigest()
        require(migration.atomic, "NONATOMIC_MIGRATION_REFUSED")

    require(
        actual == manifest["migrations"],
        "MIGRATION_FILES_CHANGED_REVIEW_REQUIRED",
    )


def missing_schema(connection):
    from django.apps import apps

    missing = []

    with connection.cursor() as cursor:
        tables = set(connection.introspection.table_names(cursor))

        for model in apps.get_models(include_auto_created=True):
            if not model._meta.can_migrate(connection):
                continue

            table = model._meta.db_table
            if table not in tables:
                missing.append(table)
                continue

            columns = {
                column.name
                for column in connection.introspection.get_table_description(
                    cursor, table
                )
            }
            missing.extend(
                f"{table}.{field.column}"
                for field in model._meta.local_fields
                if field.column not in columns
            )

    return sorted(missing)


def inspect_database(connection):
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    reviewed_graph(executor.loader)
    executor.loader.check_consistent_history(connection)

    require(
        not executor.loader.detect_conflicts(),
        "MIGRATION_GRAPH_CONFLICT",
    )
    require(
        set(executor.loader.applied_migrations)
        <= set(executor.loader.disk_migrations),
        "UNKNOWN_APPLIED_MIGRATIONS",
    )

    targets = executor.loader.graph.leaf_nodes()
    plan = executor.migration_plan(targets)

    require(
        not any(backwards for _, backwards in plan),
        "BACKWARDS_MIGRATION_REFUSED",
    )

    # Count every non-system relation, not just the tables Django knows about.
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT count(*)
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname !~ '^pg_'
              AND n.nspname <> 'information_schema'
            """
        )
        relation_count = cursor.fetchone()[0]

    missing = missing_schema(connection)
    pending = [
        f"{migration.app_label}.{migration.name}"
        for migration, _ in plan
    ]

    emit(
        f"applied_migrations={len(executor.loader.applied_migrations)} "
        f"pending_migrations={len(pending)}"
    )

    for name in pending:
        emit("pending=" + name)

    for name in missing:
        emit("missing=" + name)

    state = classify_state(pending, relation_count, missing)
    emit("schema_state=" + state)
    return state


def classify_state(pending, relation_count, missing):
    if not pending:
        return "DRIFT_REVIEW_REQUIRED" if missing else "CURRENT"

    return (
        "EMPTY_BOOTSTRAP_READY"
        if relation_count == 0
        else "PARTIAL_REVIEW_REQUIRED"
    )


def apply_empty_database(connection, state):
    from django.core.management import call_command

    if state == "CURRENT":
        emit("result=ALREADY_CURRENT_NO_CHANGES")
        return

    require(
        state == "EMPTY_BOOTSTRAP_READY",
        "NONEMPTY_OR_DRIFTED_DATABASE_REFUSED",
    )

    # The caller holds an advisory lock and outer transaction. The reviewed
    # historical migrations may remove only objects created in this fresh run.
    # No existing schema or business records are accepted for this bootstrap.
    output = io.StringIO()
    call_command(
        "migrate",
        database="default",
        interactive=False,
        verbosity=0,
        stdout=output,
        stderr=output,
        no_color=True,
    )

    require(
        inspect_database(connection) == "CURRENT",
        "POST_MIGRATION_VERIFICATION_FAILED",
    )
    emit("schema_verified=true")


def run(mode):
    # The setup wrapper catches errors before Django logging is initialized too.
    require(
        os.environ.get("DJANGO_SETTINGS_MODULE", "config.settings")
        == "config.settings",
        "UNEXPECTED_SETTINGS_MODULE",
    )
    os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"

    import django

    django.setup()

    from django.conf import settings
    from django.db import connection, transaction

    validate_target(connection, settings, os.environ)

    try:
        connection.ensure_connection()
        verify_server(connection)

        if mode == "inspect":
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    cursor.execute(
                        "SELECT set_config('statement_timeout', '60000', true)"
                    )

                state = inspect_database(connection)

            require(
                state in {"CURRENT", "EMPTY_BOOTSTRAP_READY"},
                "SCHEMA_REQUIRES_MANUAL_REVIEW",
            )
            emit("result=INSPECTED_NO_CHANGES")
            return

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_try_advisory_lock(%s)",
                [LOCK_ID],
            )
            require(
                cursor.fetchone()[0],
                "ANOTHER_BOOTSTRAP_IS_RUNNING",
            )

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('lock_timeout', '5000', true)"
                )
                cursor.execute(
                    "SELECT set_config('statement_timeout', '60000', true)"
                )

            state = inspect_database(connection)
            apply_empty_database(connection, state)

        emit(
            "result=SUCCESS pending_migrations=0 "
            "sqlite_records_transferred=0"
        )

    finally:
        # Closing the session releases its advisory lock, also on rollback.
        connection.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode",
        nargs="?",
        choices=("inspect", "apply"),
        default="inspect",
    )
    args = parser.parse_args(argv)

    try:
        run(args.mode)
    except Refused as error:
        emit("result=REFUSED reason=" + error.args[0])
        return 1
    except Exception as error:
        # Never print str(error), traceback locals, settings or the URL.
        emit("result=FAILED " + exception_summary(error))
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())