# CampusFriend catalog transfer — prepared 2026-11-08

**Preparation only. No import, production dry run, media upload or deployment has
been performed. The owner approved the export selection, not its execution.**

## Selected data and relationships

| Model | Local count | Selected count | Treatment |
| --- | ---: | ---: | --- |
| store.Category | 19 | 19 | Preserve all IDs, parent IDs, names/slugs, ordering and visibility |
| store.Product | 19 | 14 | Preserve IDs 6–19, category IDs, prices, stock, flags, timestamps and image paths |
| core.BusinessContact | 1 | 1 | Preserve ID 1 and all fields, including five populated social links |

The owner selected exclusions **2, 3, 4, 5, 20**. Nothing is removed from SQLite.
IDs 2–4 have DEMO SKUs; ID 5 explicitly describes sample prices/stock; ID 20
(`frame`) has placeholder text and a missing image. All categories stay, including
currently empty ones: they are valid taxonomy, not automatically classified as demos.

The 14 selected products total **43 stock units**. Product 16 (JBL Headphones)
has stock 0 and an existing featured flag; both are preserved, not silently
corrected. The homepage already requires positive stock for featured products.
Stock 0, NULL and unavailable flags retain their distinct meanings.

Category.parent is a protected self-reference; parents are inserted first.
Product.category is a protected reference. OrderItem.product references products,
but no local orders/items are copied and no hosted order relationship is rewritten.
BusinessContact has no foreign keys; because the footer uses the first row, a
conflicting/additional hosted contact stops the transfer instead of being merged.

Local-only records excluded by scope include 1 user, 13 orders, 18 order items,
4 order payments, 1 repair request, 41 phone models, 8 sessions and 95 admin logs,
plus related histories/notifications. Their data stays in SQLite. The existing
whole-database `transfer_database` command is not appropriate for this operation.

Django content types (22 locally), permissions (88 locally), migration history
and the six default repair services are **never included in the catalog bundle**.
No `migrate`, `loaddata`, full-database import, overwrite, deletion or reseeding
is invoked by the new importer. Existing hosted administrators/defaults remain.

BusinessContact's social links are database-driven. The current footer reads its
phone/WhatsApp/email from BUSINESS_PHONE, WHATSAPP_NUMBER and BUSINESS_EMAIL
environment settings; copying the contact row does not change those settings.

## Protection and preflight

`catalog_transfer.py` uses `core/catalog_transfer.py`. Its default action is
`check`, a read-only PostgreSQL transaction. The public CLI refuses SQLite,
DEBUG=True, an unexpected database/host/role, inactive TLS, incompatible schema,
pending/different migration histories, invalid checksums and out-of-scope models.

The transfer is insert-only. Existing rows must match every serialized field at
the same primary key to be treated as an identical no-op. A changed stock value,
price, timestamp or contact causes refusal. A matching SKU/slug/name at a
different ID also causes refusal. No IDs are renumbered and no live values win
or lose by an automatic merge. Unrelated existing catalog rows are preserved.

Imports lock only the three selected tables, use finite lock/statement timeouts,
run in one transaction, compare every selected field/relationship, and verify
all model counts. Primary-key sequences advance above both their old value and
the table maximum; they are not reset downward. Sequence advances may leave
harmless gaps after failures because PostgreSQL sequences are nontransactional.

Both `dry-run` and `commit` require a reviewed selection and an explicit approval
value equal to the exact bundle SHA-256. Check/verify do not insert any records.
Errors/logs contain only fixed reason codes, exception classes, counts and IDs;
no connection strings, payload contents, passwords or contact values are printed.

Before an approved import:

1. Confirm the exact deployed revision and target database in Render. The local
   source matched GitHub main `0d8373295f1d1b1af2daf8ff71b8c919df696147` during
   preparation. Actual hosted counts and Cloudinary state are not yet verified.
2. Confirm the source snapshot still represents the inventory you intend to
   publish. Freeze catalog/admin/checkout writes during the short transfer window.
   A new source edit needs a new snapshot, bundle hash and approval.
3. Save a protected PostgreSQL backup and record target identity/time/counts.
   Use paid-plan recovery/export if available; otherwise an approved operator
   must make a `pg_dump` backup with credentials in private environment/pgpass
   settings, not a URL command argument. Restrict any temporary external access
   to that operator's IP, then remove it. Validate the backup and rehearse restore
   to a separate empty destination. Never restore over the running database.
4. Preserve a separate protected copy of SQLite and the entire media directory.
   This preparation made a consistent private SQLite snapshot and hashed the
   original databases/environment/media files. All 40 existing media files were
   also copied to a private backup and verified by SHA-256. No images were moved
   or deleted.
5. Review the Cloudinary plan. Database rows preserve image paths, but that alone
   cannot make local product photos appear on Render. Coordinate media readiness
   before making the imported catalog available to customers.

## Private artifacts

The preparation workspace's `private/reviewed-bundle/` contains:

- `catalog.json`: only the 34 selected catalog/contact records and their metadata.
- `sha256.txt`: the digest to independently compare before approval.
- `render-env-value.txt`: gzip/base64 packaging of catalog.json for private Render
  environment delivery. **Encoding is not encryption.** Keep this file private.
- `source.sqlite3`: full local backup, including unrelated private records.
  **Never upload this file to Git or to the catalog environment variable.**

The reviewed bundle's SHA-256 is:

```text
25152c5a418c32c0f5e52e129326f446848344bd38221832a974b3648b0c99b4
```

Its private environment value is 4,752 characters. Only its safe metadata appears
in this document; do not paste the encoded contents into chat or commit them.

For a later fresh export, place the explicit review JSON under ignored
`private-transfer/` and use a new bundle directory each time:

```powershell
python catalog_transfer.py export --source db.sqlite3 --bundle private-transfer/catalog-001 --review private-transfer/selection-review.json
```

The selected review contains `reviewed: true`, `excluded_product_ids: [2,3,4,5,20]`
and `excluded_category_ids: []`. This marks reviewed content only. Export makes
a consistent read-only-source snapshot; it never imports or rewrites local data.
Keep every snapshot/export outside Git. Never upload the entire workspace.

## Render Free procedure

Render Free web services have no shell or one-off jobs; their filesystem is
ephemeral. This procedure carries the small private catalog bundle in private
environment settings and uses a temporary start command. It does not depend on
an uploaded file surviving a restart or on exposing an import HTTP endpoint.
[Render Free restrictions](https://render.com/docs/free)

Only the five prepared source/documentation files belong in Git. Use
`[skip render]` in the commit message or turn auto-deploy off before uploading.
Build command remains:

```sh
pip install -r requirements.txt && python manage.py collectstatic --noinput
```

Set these in the web service's private environment panel:

| Key | Value source |
| --- | --- |
| DATABASE_URL | Existing correct internal URL; do not paste it into code or commands |
| DEBUG | False |
| EXPECTED_DB_HOST | Independently checked database hostname |
| EXPECTED_DB_NAME | Independently checked actual database name |
| CATALOG_BUNDLE_GZIP_B64 | Contents of private render-env-value.txt |
| CATALOG_BUNDLE_SHA256 | Contents of matching sha256.txt |
| CATALOG_IMPORT_APPROVED_SHA256 | **Leave unset until the owner explicitly approves importing this hash** |

Read-only preflight start command (after installing/reviewing the prepared code):

```sh
python catalog_transfer.py check && exec gunicorn config.wsgi:application --access-logfile - --error-logfile - --capture-output
```

It reports target verification, existing counts, intended insert counts and
expected final counts. If the hosted selected tables are empty, expect +19
categories, +14 products and +1 BusinessContact; all other model counts must stay
unchanged. Existing identical rows reduce the insert counts. Any conflict stops
before Gunicorn starts on the replacement instance; the previous deploy may
continue serving. Recheck maintenance controls before any later write.

**STOP here for approval. No production check/dry-run/import ran in this task.**

After the owner approves the exact target, backup, selected bundle and write
window, set CATALOG_IMPORT_APPROVED_SHA256 to that same hash privately. First use:

```sh
python catalog_transfer.py dry-run && exec gunicorn config.wsgi:application --access-logfile - --error-logfile - --capture-output
```

Require `DRY_RUN_ROLLED_BACK`. This does perform transactional test inserts and
then rolls them back, so it also requires approval. Review all reported counts.
Then, within the approved window, use:

```sh
python catalog_transfer.py commit && python catalog_transfer.py verify && exec gunicorn config.wsgi:application --access-logfile - --error-logfile - --capture-output
```

Require `COMMITTED` (or `ALREADY_IDENTICAL_NO_CHANGES` on an unchanged repeat),
followed by `VERIFIED_NO_WRITES`. Preserve the JSON receipt with bundle hash,
inserted IDs and before/after counts in a private operations record. Verification
checks exact selected records, not only totals. Check storefront/category pages,
prices, stock=0 behavior, all five social links, admin access and images.

Restore the ordinary start command and remove the three CATALOG_* variables
after verification. Remove temporary expected-target fields if no longer needed:

```sh
gunicorn config.wsgi:application --access-logfile - --error-logfile - --capture-output
```

An unchanged repeat is a no-op. A later order, stock edit or contact edit must
never be "fixed" by rerunning the old bundle: the importer will refuse it.

## Rollback and recovery

- Before commit: checks write no data; approved dry runs and failed transactions
  roll back inserted rows. Keep snapshots and receipts. Investigate errors rather
  than bypassing checks. Sequence gaps do not imply missing business records.
- After commit, before any new live writes: code rollback alone does not undo
  database changes. Restore the verified pre-import backup into a **separate**
  database, verify it, then arrange an approved connection switch. Preserve the
  original live database; do not drop it or blindly delete imported IDs.
- After new orders/payments/admin edits: back up the current database first and
  reconcile those changes. Prefer a reviewed forward correction. Restoring the
  old backup over live data would lose new business records. Never delete
  products with order references as an automatic rollback.
- Keep original SQLite and product images intact through verification and the
  retention period. They are source backups, not a substitute for backing up new
  hosted orders. Cloudinary assets/mappings have their own recovery plan.

No actual PostgreSQL execution has been validated by the local SQLite tests.
Connection/TLS, PostgreSQL locking and sequence operations still require the
approved target rehearsal. Do not interpret local tests as live import success.
