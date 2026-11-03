# CampusFriend pre-deployment readiness

Audit date: 2026-11-03. This is a local cleanup, not a deployment approval.

## What is ready locally

- Environment-based Django and Paystack secrets; DEBUG defaults to False.
- WhiteNoise and compressed manifest static storage are configured.
- Django applications, tests, and all migrations are preserved.
- requirements.txt matches the installed pinned runtime packages; pip check passes.
- The PostgreSQL adapter (psycopg and psycopg-binary) and dj-database-url are already pinned. They are intentionally retained for the planned PostgreSQL move.

## Work required before GitHub/Render

1. **Git:** The project is connected locally to https://github.com/princeCodes07/CampusFriend-. The repository root is CampusFriend, with manage.py at the top level. Existing GitHub history is preserved on main. Review local commits and obtain the owner's approval before pushing. No push or deployment is included in the local setup.
2. **Database:** config/settings.py currently always selects SQLite. DATABASE_URL has no effect. Add and test PostgreSQL configuration while retaining SQLite locally, then plan a separate data migration. Running migrations creates schema; it does not transfer the current users, products, orders, payments, or repairs. Preserve IDs, relationships, authentication data, and media paths. Validate row counts and sequences after import. Test checkout/payment locking and concurrency against PostgreSQL, including queries that combine select_for_update() with nullable select_related() joins.
3. **Server/build:** No production application server or Render build/start configuration is included. Select and pin a suitable production WSGI/ASGI server, install requirements, run collectstatic, and define a deliberate migration/release step. The existing WSGI entry point is config.wsgi:application. Do not use Django runserver for production. Verify package installation on Render's Linux/Python runtime; the installed Windows environment alone does not prove that build.
4. **Uploads:** MEDIA_ROOT is local media/ and media URLs are served only when DEBUG=True. Configure durable upload storage and a production media-serving path before launch, and transfer existing files. CLOUDINARY_URL is currently unused. WhiteNoise static assets do not replace user-media storage. Render's default filesystem is ephemeral; a disk alone also needs a media-serving configuration. See [Render storage documentation](https://render.com/docs/disks).
5. **Environment:** Use a separate stable production secret, DEBUG=False, exact ALLOWED_HOSTS, and HTTPS CSRF_TRUSTED_ORIGINS. Configure SECURE_PROXY_SSL_HEADER only for a proxy that sanitizes the header, then verify secure redirects/cookies and callbacks. Run check --deploy against the actual production environment. Local development intentionally retains HTTP/debug settings.
6. **Payments and email:** Keep Paystack test mode until live payments are explicitly authorized. Validate both Store and Repairs public webhook/callback flows with provider test transactions. PAYSTACK_WEBHOOK_URL is a dashboard reminder, not a setting consumed by the app. Configure and test notification email separately. No real provider transactions or messages were sent during cleanup.
7. **Public assets:** static/images/SACSU_2026_2027_Revised_Budget.pdf is an authored PDF preserved locally and specifically excluded from Git. A local collectstatic can include it; keep it out of the public release unless explicitly approved. The unreferenced campus-kit.svg illustration and duplicate media images were also retained because lack of a code reference does not prove that authored data is disposable.

## Data and generated files

Keep .env, every SQLite database, uploaded media, virtual environments, caches, and local backups out of Git. The actual .env and all databases remain in place. Separate verified backups and full audit manifests are held outside the application directory. Never upload the backup folder: it contains local credentials and user data.

Keep all migrations and package __init__.py files even when empty. Both style.css and theme.css are loaded, in that order; they are not duplicate files. All 25 templates have runtime references or conventional Django lookup. staticfiles/ is generated but has been retained to avoid breaking an already-running server; rebuild it for deployment from static/ and installed app assets.

## Validation commands

Run from the project directory using its virtual environment:

~~~powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py test --noinput
.\.venv\Scripts\python.exe manage.py collectstatic --noinput
.\.venv\Scripts\python.exe manage.py check --deploy
~~~

Tests use an isolated test database. Do not run migrations, imports, flush, or data cleanup on the live local database as a substitute for tests. If Windows rejects temporary test uploads, point TEMP and TMP to a writable local directory for the test process.

Deployment references: [Render Django guide](https://render.com/docs/deploy-django) and [Django 5.2 deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
