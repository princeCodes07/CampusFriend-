from contextlib import redirect_stdout
import io
import logging
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from config.safe_logging import SafeExceptionFormatter, exception_summary
from render_postgres import (
    Refused,
    apply_empty_database,
    classify_state,
    main,
    reviewed_graph,
    validate_target,
    verify_server,
)


class RenderDiagnosticTests(SimpleTestCase):
    def setUp(self):
        self.settings = SimpleNamespace(DEBUG=False)
        self.connection = SimpleNamespace(
            vendor="postgresql",
            settings_dict={
                "HOST": "example.internal",
                "NAME": "example_db",
                "USER": "example_role",
                "OPTIONS": {"sslmode": "require"},
            },
        )
        self.environ = {
            "RENDER": "true",
            "DATABASE_URL": "private-test-placeholder",
            "EXPECTED_DB_HOST": "example.internal",
            "EXPECTED_DB_NAME": "example_db",
        }

    def test_matching_target_passes_without_connecting(self):
        validate_target(self.connection, self.settings, self.environ)

    def test_wrong_database_host_and_unsafe_settings_fail_closed(self):
        cases = [
            ("EXPECTED_DB_HOST", "other.internal"),
            ("EXPECTED_DB_NAME", "other"),
            ("DATABASE_URL", ""),
            ("RENDER", ""),
            ("EXPECTED_DB_NAME", ""),
        ]

        for key, value in cases:
            with self.subTest(key=key, value=value):
                with self.assertRaises(Refused):
                    validate_target(
                        self.connection,
                        self.settings,
                        {**self.environ, key: value},
                    )

        self.settings.DEBUG = True
        with self.assertRaisesRegex(Refused, "DEBUG_MUST_BE_FALSE"):
            validate_target(self.connection, self.settings, self.environ)

    def test_sqlite_is_refused_even_with_a_database_url(self):
        self.connection.vendor = "sqlite"

        with self.assertRaisesRegex(Refused, "SQLITE_REFUSED"):
            validate_target(self.connection, self.settings, self.environ)

    def test_unencrypted_config_and_connection_are_refused(self):
        self.connection.settings_dict["OPTIONS"]["sslmode"] = "disable"

        with self.assertRaisesRegex(Refused, "TLS_REQUIRED"):
            validate_target(self.connection, self.settings, self.environ)

        self.connection.connection = SimpleNamespace(
            pgconn=SimpleNamespace(ssl_in_use=False)
        )

        with self.assertRaisesRegex(Refused, "TLS_NOT_ACTIVE"):
            verify_server(self.connection)

    def test_classifies_empty_partial_and_drifted_schema(self):
        self.assertEqual(
            classify_state(["store.0001"], 0, ["store_product"]),
            "EMPTY_BOOTSTRAP_READY",
        )
        self.assertEqual(
            classify_state(["store.0001"], 1, ["store_product"]),
            "PARTIAL_REVIEW_REQUIRED",
        )
        self.assertEqual(
            classify_state([], 1, ["store_product"]),
            "DRIFT_REVIEW_REQUIRED",
        )
        self.assertEqual(
            classify_state([], 25, []),
            "CURRENT",
        )

    def test_nonempty_or_drifted_database_never_calls_migrate(self):
        with patch("django.core.management.call_command") as migrate:
            for state in [
                "PARTIAL_REVIEW_REQUIRED",
                "DRIFT_REVIEW_REQUIRED",
            ]:
                with self.subTest(state=state):
                    with self.assertRaises(Refused):
                        apply_empty_database(self.connection, state)

            migrate.assert_not_called()

    def test_current_database_is_noop(self):
        with (
            patch("django.core.management.call_command") as migrate,
            redirect_stdout(io.StringIO()) as out,
        ):
            apply_empty_database(self.connection, "CURRENT")

        migrate.assert_not_called()
        self.assertIn("ALREADY_CURRENT_NO_CHANGES", out.getvalue())

    def test_empty_bootstrap_uses_normal_forward_migrate_and_verifies(self):
        with (
            patch("django.core.management.call_command") as migrate,
            patch(
                "render_postgres.inspect_database",
                return_value="CURRENT",
            ) as verify,
            redirect_stdout(io.StringIO()),
        ):
            apply_empty_database(self.connection, "EMPTY_BOOTSTRAP_READY")

        self.assertEqual(migrate.call_args.args, ("migrate",))
        self.assertEqual(
            migrate.call_args.kwargs["database"],
            "default",
        )
        self.assertFalse(migrate.call_args.kwargs["interactive"])
        self.assertNotIn("fake", migrate.call_args.kwargs)
        verify.assert_called_once_with(self.connection)

    def test_failed_postcheck_does_not_report_success(self):
        with (
            patch("django.core.management.call_command"),
            patch(
                "render_postgres.inspect_database",
                return_value="DRIFT_REVIEW_REQUIRED",
            ),
            self.assertRaisesRegex(
                Refused,
                "POST_MIGRATION_VERIFICATION_FAILED",
            ),
        ):
            apply_empty_database(self.connection, "EMPTY_BOOTSTRAP_READY")

    def test_manifest_matches_all_installed_migrations_and_rejects_changes(self):
        from django.db.migrations.loader import MigrationLoader

        loader = MigrationLoader(None)
        reviewed_graph(loader)
        loader.disk_migrations.pop(next(iter(loader.disk_migrations)))

        with self.assertRaisesRegex(Refused, "MIGRATION_FILES_CHANGED"):
            reviewed_graph(loader)

    def test_main_defaults_to_inspection_and_redacts_errors(self):
        with patch("render_postgres.run") as run:
            self.assertEqual(main([]), 0)
            run.assert_called_once_with("inspect")

        with (
            patch(
                "render_postgres.run",
                side_effect=RuntimeError("postgres://user:SECRET@host/db"),
            ),
            redirect_stdout(io.StringIO()) as out,
        ):
            self.assertEqual(main(["apply"]), 1)

        self.assertEqual(
            out.getvalue().strip(),
            "result=FAILED RuntimeError",
        )

    def test_django_error_log_keeps_frames_and_sqlstate_without_credentials(self):
        marker = "PRIVATE-password-cookie-token"
        cause = RuntimeError(marker)
        cause.sqlstate = "42P01"

        try:
            raise ValueError(marker) from cause
        except ValueError as error:
            record = logging.LogRecord(
                "django.request",
                logging.ERROR,
                __file__,
                1,
                "URL " + marker,
                (),
                (type(error), error, error.__traceback__),
            )
            record.request = {"password": marker}
            record.exc_text = marker
            record.status_code = 500
            result = SafeExceptionFormatter().format(record)

        self.assertIn("status=500", result)
        self.assertIn("ValueError sqlstate=42P01", result)
        self.assertIn("test_render_diagnostic.py", result)
        self.assertNotIn(marker, result)
        self.assertEqual(
            exception_summary(cause),
            "RuntimeError sqlstate=42P01",
        )
        