# PostgreSQL readiness and operator runbook

Prepared 2026-11-03. This step does not authorize deployment or a live data move.
Keep the working SQLite database as the source of truth until a separately
approved cutover. Never run flush, drop, destructive restore, or migration rollback
against it. No PostgreSQL credentials belong in chat, Git, shell arguments or logs.

## Configuration now implemented

- `DATABASE_URL` selects PostgreSQL through `dj-database-url`. Only `postgres://`
  and `postgresql://` are accepted. Invalid URLs fail closed with a redacted error.
- Blank/unset URL retains `BASE_DIR/db.sqlite3` for local development, regardless
  of DEBUG. On Render (`RENDER=true`), a missing URL is an error, preventing an
  accidental ephemeral SQLite deployment.
- TLS defaults to `sslmode=require`; weaker modes are rejected. `verify-ca` and
  `verify-full` remain available with an appropriate trust configuration. Render's
  internal endpoint uses self-signed certificates, so use `require` there.
- Connection health checks are enabled; `DB_CONN_MAX_AGE` defaults to 60 seconds
  (range 0–600; use 0 for ASGI). Connect timeout defaults to 10 seconds (range 1–60).
- URL query options are limited to `sslmode`, `sslrootcert`, `connect_timeout`,
  and `application_name`. Query parameters cannot silently replace the host/user.
- Exported environment variables take precedence over the local `.env` file.
  The existing `.env` is unchanged. `.env.example` contains no database password.
- Requirements retain the installed versions: Django 5.2.17, dj-database-url 3.1.2,
  and psycopg 3.3.5. `psycopg[binary]==3.3.5` expresses the matching binary extra
  directly. A Linux install/build must still be verified in the chosen runner.
- Checkout and repair initialization lock their own rows explicitly, avoiding
  PostgreSQL's prohibition on locking the nullable side of an outer join. Repair
  verification follows the same repair-then-payment lock order as initialization.

## What the transfer preserves

The `transfer_database` management command exports every managed application
model, including hidden products, category parents, users/password hashes,
groups/custom permissions and M2M membership, orders/items/payments/history,
repair configuration/requests/payments/notes/notifications/history, business
contact settings, admin history and sessions. It preserves business primary keys,
foreign keys, monetary values, UUIDs, JSON, NULLs, image paths and full timestamp
precision. Content types and permissions use natural keys so Django-generated IDs
can differ between databases. No notification or payment workflows are invoked.

Uploaded image bytes are separate files and **must be backed up/transferred
separately**. The database move does not configure Cloudinary or durable media
hosting. Session rows are preserved; using a different Django signing secret or
domain can still invalidate existing logins/guest cookies. Plan that transition
explicitly; do not copy secrets into the bundle.

Export opens SQLite read-only and uses SQLite's backup API for a consistent
snapshot, including committed WAL data. It checks integrity, foreign keys,
table coverage and migration history. A newly created private bundle contains
`source.sqlite3`, `fixture.json`, and `manifest.json`. Existing bundles are never
overwritten. A missing manifest means an export did not finish.

The manifest includes the fixture SHA-256, version, migrations and row counts.
This detects accidental corruption, not malicious replacement; trust only your
own securely held bundle. It contains personal data, password hashes, payment
details and session tokens. Restrict filesystem access, use an encrypted backup
location outside public sync folders, and never attach it to chat or a PR.
`private-transfer/` is ignored by Git; protect copies made elsewhere too.

## Human-operated Render checklist — do this before any connection

1. In Render choose **New → Postgres**. Name the database clearly, such as
   `campusfriend-staging`. Choose the same account/region as the future Django
   service. Choose PostgreSQL 14 or newer, supported by Django 5.2; record the
   chosen major version for rehearsal. Confirm the price and storage yourself.
2. Keep rehearsal and final data destinations separate. Select a plan with the
   retention/recovery you require. Paid databases provide point-in-time recovery
   and exports; the Free plan has no recovery capabilities. Check the database's
   Recovery page and retention before entrusting it with the only copy of data.
3. Under Networking, replace the default open external IP range with the
   operator/runner's required IP ranges only. Disable external access when no
   longer needed. Render-internal connections use the private endpoint.
4. Privately store the appropriate URL as `DATABASE_URL` in the migration
   runner's **platform environment settings**. Use the internal URL for a runner
   in the same Render account/region, the external URL for an outside runner.
   Preserve the full hostname. Keep TLS required. Use direct Postgres port 5432
   for this transfer rather than introducing a connection pooler.
5. Store `DJANGO_SECRET_KEY` privately too. Set `DEBUG=False` and
   `DB_CONN_MAX_AGE=60` for the eventual WSGI service; retain Paystack test mode.
   For this preparation you can use an unlinked environment group. Do not attach
   an empty database to an active app, save-and-deploy, or enable auto-deploy.
6. **Pause here.** Confirm only that private settings are ready, plus the database
   role (rehearsal/final), region and major version. Do not send credentials. The
   remaining commands are for the separately approved rehearsal/cutover window.

Render references: [create/connect and networking](https://render.com/docs/postgresql-creating-connecting),
[recovery and backups](https://render.com/docs/postgresql-backups).
Django references: [PostgreSQL requirements](https://docs.djangoproject.com/en/5.2/ref/databases/#postgresql-notes),
[serialization and natural keys](https://docs.djangoproject.com/en/5.2/topics/serialization/#natural-keys).

## Export on the source computer

Use this exact code version and its pinned requirements. Stop writes during the
final snapshot: checkout, admin edits, payment/webhook processing, repairs and
background writers. A rehearsal snapshot can be taken earlier, but later source
changes will require another final export. Make a separate protected media backup.

From `Commerce/CampusFriend`, with the local virtual environment active:

```powershell
python manage.py check
python manage.py makemigrations --check --dry-run
python manage.py transfer_database export --source db.sqlite3 --bundle private-transfer/final-001
```

Choose a fresh bundle name for every export. Do not print its contents. If the
source has pending migrations, stop and investigate; migrate a separate SQLite
copy after backup/review, never change the live source just to make export pass.
Transfer the complete bundle securely to the chosen runner, outside its public
directory. Do not upload it through Git or put credentials in an archive.

## Rehearse on a fresh PostgreSQL destination (not yet executed)

The runner must already have its credentials in private platform environment
settings. Verify the destination in the platform UI before running commands.
Keep the app and all writers disconnected. Do not create a superuser or seed a
catalog first; the source already contains these records.

```text
python -m pip install -r requirements.txt
python -m pip check
python manage.py check --database default
python manage.py migrate --plan
python manage.py migrate --noinput
python manage.py transfer_database import --bundle private-transfer/final-001
```

`migrate` creates only the fresh target schema and the six built-in repair-service
seeds; it does not copy business data. Review its plan first. The import above is
a **dry run**: it inserts within a transaction, validates constraints and compares
every serialized record and relationship, then rolls back all inserted rows.
PostgreSQL sequences can acquire harmless gaps during rolled-back inserts.

The importer checks identical migration history/model coverage, locks target
tables with a five-second timeout, and rejects occupied or changed targets.
Only matching content types/permissions and the six exact migration seed rows
are allowed beforehand. If a source has removed/rekeyed these seed rows or added
unmodeled tables, stop for a reviewed mapping; there is no force/overwrite flag.
Admin history pointing to content-type/permission objects also requires an
explicit ID-mapping review; ordinary business-object admin history is preserved.

After reviewing a successful rehearsal, on the explicitly selected destination:

```text
python manage.py transfer_database import --bundle private-transfer/final-001 --commit
python manage.py transfer_database verify --bundle private-transfer/final-001
python manage.py transfer_database import --bundle private-transfer/final-001 --commit
```

Commit occurs only after constraint checks and full record comparison. Primary-key
sequences, including automatic M2M tables, are reset and checked for collisions.
The repeat command is a verified no-op when everything already matches. Any
subsequent data change causes re-import to be refused, not overwritten. A failed
transaction rolls back records; PostgreSQL sequence changes are nontransactional
and may leave gaps. Do not retry into a database with live users/writers.

On a **separate disposable PostgreSQL test database/instance** and with a role
permitted to create the Django test database, run:

```text
python manage.py test --noinput
```

Django creates/destroys its test database: never aim tests at the production
instance or a valuable database named `test_*`. Verify the full suite, checkout,
repair payment creation, and simultaneous duplicate payment/checkout handling
against PostgreSQL. SQLite does not establish PostgreSQL locking/concurrency,
TLS/network access, sequence behavior or Render build compatibility.
Build the isolated runner's static manifest with `python manage.py collectstatic
--noinput` before the full suite; several existing repair tests render templates
with manifest storage enabled. Run that only in a reviewed release/test copy so
unapproved local reference assets are not included in a public build.

## Final cutover, verification and rollback

Do not deploy during this readiness step. A later approved cutover requires:

1. Freeze source writes, back up SQLite/media, export a final fresh bundle, and
   repeat the verified procedure into a fresh final PostgreSQL database.
2. Verify all records with the command before allowing writes. Review counts in
   the private manifest and sample catalog, user login, order items/totals/history,
   repair details/history, admin permissions, uploaded images, and a new record
   on the rehearsal destination to confirm IDs advance. Test provider calls only
   with authorized test credentials; this work sends no payments or emails.
3. Ensure durable media hosting, application server/build settings, HTTPS and
   environment configuration are separately ready. Create a protected PostgreSQL
   backup and verify the Recovery options before opening the app to users.
4. Only then switch the approved service to the final private `DATABASE_URL` and
   resume writes. Keep original SQLite, source code version and media backups.

Before new PostgreSQL writes, rollback means keeping/restarting the original
SQLite app with its original environment. Do not delete the PostgreSQL database.
After any new PostgreSQL writes, stop and reconcile them first; blindly switching
back would lose new orders/payments/repairs. Do not merge by rerunning the import.
This utility intentionally supports fresh-target transfer, not ongoing replication.
