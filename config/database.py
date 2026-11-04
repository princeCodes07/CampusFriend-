"""Database selection without logging or embedding connection credentials."""

from urllib.parse import parse_qsl, urlsplit

import dj_database_url
from django.core.exceptions import ImproperlyConfigured


def database_config(base_dir, environ):
    url = environ.get("DATABASE_URL", "").strip()
    # Render must never silently create an ephemeral SQLite database.
    if not url:
        if environ.get("RENDER", "").lower() == "true":
            raise ImproperlyConfigured("Set DATABASE_URL privately in Render's environment settings.")
        return {"ENGINE": "django.db.backends.sqlite3", "NAME": base_dir / "db.sqlite3"}

    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise ValueError
        if not parsed.hostname or not parsed.username or not parsed.path.strip("/") or parsed.fragment:
            raise ValueError
        # Never allow URL query parameters to replace the actual destination.
        allowed = {"sslmode", "sslrootcert", "connect_timeout", "application_name"}
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if any(key not in allowed for key, _ in pairs) or len({k for k, _ in pairs}) != len(pairs):
            raise ValueError
        config = dj_database_url.parse(url, conn_max_age=60, conn_health_checks=True)
        options = config.setdefault("OPTIONS", {})
        sslmode = options.setdefault("sslmode", "require")
        if sslmode not in {"require", "verify-ca", "verify-full"}:
            raise ValueError
        options["connect_timeout"] = int(options.get("connect_timeout", 10))
        if not 1 <= options["connect_timeout"] <= 60:
            raise ValueError
        age = int(environ.get("DB_CONN_MAX_AGE", "60"))
        if not 0 <= age <= 600:
            raise ValueError
        config["CONN_MAX_AGE"] = age
        return config
    except (ValueError, TypeError, KeyError):
        # Parser errors can contain the supplied URL; never chain them.
        raise ImproperlyConfigured(
            "Invalid database configuration. Use a PostgreSQL DATABASE_URL with "
            "URL-encoded credentials, TLS (require/verify-ca/verify-full), "
            "connect_timeout 1-60, and DB_CONN_MAX_AGE 0-600."
        ) from None
