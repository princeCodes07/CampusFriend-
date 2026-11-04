# CampusFriend

Django foundation for a mobile-first student ecommerce and services application
at KNUST Campus, Ghana. The storefront includes product browsing, categories,
books, search, product details, a guest cart, and guest order requests, with
Django Admin catalog management and delivery quote confirmation.

## Automatic delivery pricing

Checkout has one fixed **Select location** field. Campus delivery and pickup at
Palms Eatery are free. Ayeduase, Kotei, Boadi and Newsite each add GHS 10.00.
**Other location** charges for items only; delivery is discussed and paid separately.
Every new order is immediately payable without admin approval. Locations and fees
are hardcoded on the server in `orders/delivery.py`; there is no delivery-zone
model, table, or admin setup. The old `CHECKOUT_DELIVERY_FEE` setting is ignored.

See [delivery pricing operations](DELIVERY_PRICING_V1.md) for migration, admin
setup, payment safeguards, and launch verification.

## Local Setup (Windows PowerShell)

The shared visual theme lives in `static/css/theme.css`, loaded after the
structural styles in `static/css/style.css`. It provides fluid spacing, rounded
surfaces, responsive product cards and short motion effects that respect
`prefers-reduced-motion`. The homepage hero uses existing featured product data
and images. Navigation and checkout work without animation. After changing static
assets, run `manage.py collectstatic --noinput` to refresh the production manifest.

Open a terminal in this directory, `Commerce\CampusFriend`.
Python 3.13 was used for initial setup. Use `python` on this machine because its
`py` launcher does not locate the installed interpreter.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

If PowerShell permits scripts, activate with `. .\.venv\Scripts\Activate.ps1`.
If activation is blocked by execution policy, the explicit Python path above
works without changing that policy. In Command Prompt, you can instead use
`.venv\Scripts\activate.bat`.

Create the ignored local `.env` file once from the example:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env`, generate a development key once, and paste it after
`DJANGO_SECRET_KEY=`:

```powershell
.\.venv\Scripts\python.exe -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Keep `DEBUG=True` and `ALLOWED_HOSTS=127.0.0.1,localhost,[::1]` in `.env` for
local development. Django loads this file automatically, so no per-terminal
environment assignments are needed. Keep the same key between runs; generating
a replacement invalidates existing sessions and signed links. A future
production environment needs its own stable, securely configured key.

`.env.example` documents variable names. Django loads the ignored local `.env`
file at startup; values already exported in the shell take precedence. Keep real
credentials only in `.env` or the deployment environment, never in source files.
A missing or empty DJANGO_SECRET_KEY causes a clear configuration error; there
is no hardcoded fallback. DEBUG defaults to False, so set it explicitly for
development. SQLite is the only configured database at this stage.

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver
```

Visit http://127.0.0.1:8000/ for the storefront and
http://127.0.0.1:8000/admin/ for Django Admin. Stop the server with Ctrl+C.
Model, admin, storefront, cart, checkout and payment tests run with
`manage.py test`. Live courier tracking remains a future capability; Repairs
supports guest requests, fixed-price payments, status tracking, and operational notifications.

## Storefront Pages

| URL | Page |
| --- | --- |
| `/` | Compact hero, populated categories, featured/latest products, Repairs, and available Books |
| `/shop/` | Catalog, 12 products per page |
| `/shop/department/<slug>/` | Compatibility redirect to the matching category, preserving query parameters |
| `/shop/?q=charger` | Search names, descriptions, and SKUs |
| `/shop/category/<slug>/` | Active category and its available products |
| `/shop/product/<slug>/` | Product information, quantity selection, and Add to cart |
| `/cart/` | Guest cart, total quantity, subtotal, and item removal |
| `/checkout/` | Guest contact details, campus delivery or pickup, and order summary |
| `/orders/` | Orders saved in this browser and their latest status |
| `/orders/<reference>/` | Saved order confirmation, restricted to the guest's session |
| `/books/` | Products in the Books category |
| `/repairs/` | Repair catalogue and student repair experience |
| `/repairs/<reference>/` | Session-protected repair detail and status |
| `/track/` | Compatibility redirect to `/orders/`, owned by Orders |

### URL ownership

Core owns the homepage. Store owns catalog and Books routes; Orders owns cart,
checkout, guest order tracking and Commerce payment routes; Repairs owns all
`/repairs/` routes. Link to `repairs:home` for repair services and
`orders:order_list` for guest order tracking. The obsolete Core Repairs and
tracking placeholders have been removed. `/repairs/` has one route owner,
independent of the order of app includes.

`orders:track` and `store:department` are deliberate compatibility redirects;
new navigation uses the canonical destinations. No public bookmark or payment
callback/webhook path has been removed. Tracking continues to show only orders
owned by the current guest session, with no login or reference-only lookup.
Request-only phone services link to `repairs:special_phone_request`, while
supported fixed-price services use `repairs:phone_service`.

All public catalog pages use the same visibility rule: the product must be
available and its category active. Out-of-stock products remain visible and
labelled. Hidden products/categories return 404. Search and category/book
listings share pagination and product cards. Search text is escaped normally.

The compact header has Home, Store, Repairs, Books, and Track Order, with global
product search beside the logo and a working cart count. Sign In will be added
when customer authentication exists. Search covers the full visible catalog.
Store category links are populated dynamically and omit empty or hidden-only
collections. Existing `/shop/department/<slug>/` URLs remain compatible for
bookmarks, but empty departments are not promoted in navigation.

The homepage reuses product cards for up to eight featured products and eight
latest products ordered by `created_at` (newest first, with ID as a tie-breaker).
It shows up to four Books/Study Materials products when available. Featured
selection uses the Admin flag; no sales rankings, ratings or popularity are
invented. Repairs links to the student-facing repair experience.

Set the Books category slug to `books`, or change `BOOKS_CATEGORY_SLUG` in
`config/settings.py`. An active category named Books is the fallback. Products
in an active `study-materials` category are included even if Books is missing.
If neither collection has products, the page is empty. No separate Book model is used.

The mobile menu works without JavaScript as an expanded navigation. JavaScript
adds menu toggling, Escape-to-close, and a fallback for failed product images.
Cart actions use CSRF-protected POST requests. There are no frontend frameworks,
web fonts or external asset requests. Placeholders and icons are local SVGs.

Set `BUSINESS_PHONE`, `WHATSAPP_NUMBER`, and `BUSINESS_EMAIL` in the environment
before starting the server to display your verified contact details. Empty
values are omitted; no raw placeholders appear to customers. The ignored `.env`
file is loaded automatically; exported environment values take precedence.

## Manage the Catalog

**Start with [the product entry guide](catalog/README.md).** Add actual products
and photos in [Django Admin](http://127.0.0.1:8000/admin/store/product/), or edit
[`catalog/products.json`](catalog/products.json) and validate/import it with:

```powershell
.\.venv\Scripts\python.exe manage.py import_products catalog/products.json --dry-run
.\.venv\Scripts\python.exe manage.py import_products catalog/products.json
```

Imports validate every entry, update by SKU, and preserve existing photos and
product URLs. The file contains 14 owner-supplied Accessories listings and prices.
Unconfirmed stock is `null`, displayed as Availability to be confirmed.
Upload photos through Admin, which includes a preview and a storefront link.

The shop supports name, price, and newest-first sorting, plus an in-stock filter.
Filters work with search and pagination. Product pages show up to four visible
related products from the same category. The Books page also includes products
in an active category with slug `study-materials`.

Sign in at `/admin/` and open **Store > Categories** or **Store > Products**.
Create a category first, then add products with a unique SKU and a price in GHS.
The product list supports search and category, availability, and featured filters.

- Names and SKUs are required; category names, SKUs, and slugs are unique.
- Slugs are prepopulated in the admin. On ordinary model saves, a blank slug is
  generated from the name with a numeric suffix if needed. Renaming an item
  preserves its slug; edit or clear the slug explicitly to change it.
- Supply unique slugs explicitly for bulk inserts, which bypass model save hooks.
  Database uniqueness is the final guard, including concurrent writes.
- Prices use two decimal places and cannot be negative. Old price is optional
  and must be strictly higher than the current price, enforced in Admin, imports
  and the database. Clear it or raise it before increasing the current price past
  it. Templates only cross out a valid higher previous price.
- Stock is a nonnegative integer or blank (`null`) when unconfirmed, the default.
  `is_in_stock` requires a known quantity above zero. Zero means out of stock;
  availability and category activity remain separate controls.
- Categories containing products cannot be deleted. Deactivate them or reassign
  their products first.
- Images and descriptions are optional. Uploaded images go into ignored
  `media/products/` and their links work locally with DEBUG=True. Production
  image hosting is deferred to the Cloudinary milestone.

Automated tests use a separate database and temporary image storage. For the
Milestone 3 browser review, five local development samples are added through
the Django shell: a power bank, charger, earbuds, Atomic Habits, and The
Psychology of Money, in Phone Accessories, Audio, and Books. Their SKUs start
with `DEMO-`; prices and descriptions are illustrative, and images use the
placeholder. These five records are now hidden after importing the owner's
14 real Accessories listings. They remain in Admin for reference and would
display Sample listing if re-enabled. Use a SKU without `DEMO-` for real listings.
Sample data stays in ignored SQLite and is not seeded by application code.

## Review Add to Cart

1. In Admin, give a published product its actual positive **Stock** quantity.
   Its category must be active. Blank or zero stock cannot be added to a cart.
2. Open the shop and click **Add to cart**, or choose a quantity on a product page.
3. The cart page opens and the header badge shows the total number of units.
   Adding the same product again increases its quantity, up to available stock.
4. Browse to another page or refresh: the same browser session keeps the cart.
   Click the header bag to reopen it. **Remove** deletes the whole product line.

Prices and subtotals are calculated from the current database prices; browser
values are ignored. Stock or visibility changes adjust saved carts automatically.
Adding does not reserve or reduce inventory. Continue to checkout submits an
order request; payment options appear after the final total is confirmed and
Paystack has been configured. All listed locations confirm automatically,
including Other location with delivery excluded from online payment.
Separate browsers have separate carts. Sessions expire normally; changing the
development secret key or clearing cookies also makes an old cart inaccessible.

Cart behavior lives in `orders/cart.py`, POST handling in `orders/views.py`,
quantity validation in `orders/forms.py`, the header count in
`orders/context_processors.py`, and the cart page in `templates/orders/cart.html`.
No new database migration is needed: carts use Django's existing session table.

## Review Checkout and Orders (Phase B)

1. Add an in-stock product to your cart and click **Continue to checkout**.
2. Enter your name and phone, with optional email. Select Campus, Pickup (Palms
   Eatery), Ayeduase, Kotei, Boadi, Newsite, or Other location. Address and landmark
   are required for delivery and optional for pickup. Delivery notes are optional.
3. Review the server-calculated total. Campus and pickup add zero; Ayeduase,
   Kotei, Boadi and Newsite each add GHS 10.00. Other location has no online
   delivery charge: its fee must be discussed and settled separately.
4. The saved order shows its unique reference and **Awaiting payment** immediately.
   Payment stays **Unpaid** until Paystack verification. The order keeps item,
   selected-location and fee snapshots. Submission clears the cart.
   Save the reference; this confirmation page works while your guest session is active.
5. Pay from the order page; no admin confirmation is required. Legacy orders
   saved before automatic pricing retain their existing quote workflow. Staff
   can still confirm those old orders through the protected admin quote action.

No payment is collected at checkout. Quote-pending and awaiting-payment orders
do not reserve or reduce stock. Current stock and product visibility are
rechecked before Paystack initialization, but stock is not reserved during
payment. The planned order flow is:

`QUOTE_PENDING → AWAITING_PAYMENT → PAID → PROCESSING → OUT_FOR_DELIVERY → DELIVERED`

Payment status is separate from fulfilment status. Payment is marked paid only
after server verification; successful payment does not itself advance fulfilment.
Only quote confirmation changes the fulfilment status automatically. There is no
automated email/SMS notification or live courier tracking.

Checkout reloads visible products, current prices and available quantities before
transactionally saving the order and its item snapshots. If something changes,
the customer must review again. A unique checkout token prevents double submits
from creating another order, even without JavaScript. Browser-supplied prices,
totals, stock and statuses are ignored. Snapshot names, SKUs, prices and amounts
survive later catalog edits/deletions. Admin cannot edit these snapshots or
independently set the total. Product deletion only clears the optional reference.

## Paystack Test Payments

Paystack payment is available only after an order's delivery quote is confirmed
and the final total is greater than zero. In your Paystack Dashboard, open the
API keys section and copy the **Test** public and secret keys into the matching
`PAYSTACK_PUBLIC_KEY` and `PAYSTACK_SECRET_KEY` entries in the ignored local
`.env` file. Do not paste a secret key into chat, commit it, or put it in
`.env.example`. Keep `PAYSTACK_LIVE_MODE=False`; test keys enable hosted checkout.
Test keys are never sent to the browser; live keys are rejected unless
`PAYSTACK_LIVE_MODE=True` is explicitly set after live payments are authorized.
Restart Django after editing `.env`; it loads the file at startup. Shell or
deployment environment variables take precedence over values in `.env`.

Payment initialization rechecks current product visibility and stock. Stock is
not reserved, so availability can still change after the customer is redirected
to Paystack. Paystack callbacks are verified by the server. The webhook checks
the raw-body `X-Paystack-Signature`, event, reference, amount and currency before
marking a payment paid. Configure the Paystack webhook URL as
`https://<your-public-host>/orders/payments/paystack/webhook/`; local development
servers are not publicly reachable by Paystack.

Each retry uses a new payment record and unique reference. Payment success
updates payment status only; it does not advance the separate order fulfilment
status or reserve stock. A customer can view recorded order status and payment
details from the session-protected order page. This is not live courier tracking.

The payment migration adds payment records. Paystack API access
is isolated in `orders/payments.py`; order creation and payment-attempt
validation remain in `orders/services.py`.

## Repairs Notifications and Production Settings

Repairs records one email notification per repair, event, and channel. Email is
sent only when `EMAIL_BACKEND` is the SMTP backend and `EMAIL_HOST` plus
`DEFAULT_FROM_EMAIL` are configured. Set `EMAIL_PORT`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, and `EMAIL_TIMEOUT`
for the chosen SMTP service. Keep credentials in the ignored `.env` file or
deployment secret manager; `.env.example` contains placeholders only. Without
SMTP host/sender configuration a notification is recorded as failed, never
reported as sent. Admin can inspect and retry failed email notifications.
Delivery via SMS or WhatsApp is not configured.

Configure the Repairs Paystack webhook as
`https://<your-public-host>/repairs/payments/paystack/webhook/`. It requires a
public HTTPS endpoint and matching environment-managed Paystack keys. A real
sandbox transaction/webhook and SMTP delivery must be verified from an external
staging environment; local tests mock provider delivery.

Keep `PAYSTACK_LIVE_MODE=False` and use matching Paystack test keys for Stage 7
sandbox work. `PAYSTACK_WEBHOOK_URL` in `.env` or deployment configuration is
an operator reminder for the Paystack Dashboard target; Django does not use it
to change the webhook route or bypass request-derived callback URLs.

With `DEBUG=False`, SSL redirect, secure session/CSRF cookies, and one-year HSTS
default on. Set `ALLOWED_HOSTS` to the deployment hostnames and
`CSRF_TRUSTED_ORIGINS` to comma-separated HTTPS origins when cross-origin admin
or form requests require them. Set
`SECURE_PROXY_SSL_HEADER=HTTP_X_FORWARDED_PROTO,https` only when the selected
trusted reverse proxy strips client-supplied forwarded headers and sets its own
value. Leave it blank otherwise. Configure HSTS subdomains/preload only after
confirming every covered host is HTTPS. Individual security settings can be
explicitly overridden by environment variables for the hosting topology.

## Paystack Production Checklist

Live payments are deliberately disabled by default. `PAYSTACK_LIVE_MODE`
defaults to `False` independently of `DEBUG`; setting `DEBUG=False` does not
enable live payments. Use matching `pk_test_...` and `sk_test_...` credentials
for development and staging tests. Live transactions require an explicit
`PAYSTACK_LIVE_MODE=True` deployment setting and matching `pk_live_...` and
`sk_live_...` keys. With live mode enabled, test credentials or incomplete or
mismatched keys are rejected. Do not commit credentials or place them in
`.env.example`, documentation, source code, templates or tests.

Before enabling live payments:

1. Deploy behind HTTPS and configure the provider's webhook URL as
   `https://<your-public-host>/orders/payments/paystack/webhook/`.
2. From outside the local network, confirm the endpoint is publicly reachable
   and POST requests reach Django.
3. Confirm the deployment proxy forwards `X-Paystack-Signature` to Django
   unchanged.
4. Confirm on the deployed staging environment that a missing or invalid
   signature receives HTTP 401 and a valid Paystack-signed test webhook is
   processed.
5. Confirm responses and application logs do not expose either key.
6. Use Paystack test credentials for development; only deliberately enable live
   payments with production-managed live credentials after staging verification.

This repository has no deployment or reverse-proxy configuration. The
reachability, HTTPS, request forwarding and deployed webhook checks above
therefore require a real staging deployment; Django tests cannot verify them.

The fixed delivery policy lives in `orders/delivery.py`; no zone setup is needed.
Saved orders retain their location and fee snapshots. Other-location delivery is
always separate from online payment, including after the items are paid for.
Legacy quote changes invalidate previous payment attempts; paid orders remain
protected. All delivery summaries are usable without JavaScript; JavaScript
selects the summary without calculating money.

The `orders/0001_initial` migration adds Order and OrderItem. Business operations
are in `orders/services.py`, models in `orders/models.py`, forms in `orders/forms.py`,
and new templates in `orders/templates/`. `orders/test_checkout.py` covers
checkout, snapshots, validation, permissions, quoting and duplicate protection.

## Create Your Administrator

After migrating, run this in the terminal with the environment configured:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Supply your chosen `[ADMIN_USERNAME]` and `[ADMIN_EMAIL]`, then enter the password
privately at the hidden terminal prompt. Do not send the password in chat or
store it in documentation, source code, environment examples, or Git.

## Git and GitHub

The Git repository root is this CampusFriend directory, beside manage.py.
The origin remote is [princeCodes07/CampusFriend-](https://github.com/princeCodes07/CampusFriend-).
The trailing hyphen is part of the repository name. The main branch preserves
its existing GitHub history; current development is recorded in local commits.
Pushing and deployment require the owner's approval.

Open this folder in VS Code to view its Source Control history. For a fresh copy:

~~~powershell
git clone https://github.com/princeCodes07/CampusFriend-.git
~~~

Review changes and file names before committing:

~~~powershell
git status --short
git diff
git diff --cached --stat
git diff --cached --check
~~~

Keep .env, databases, uploaded media, virtual environments, generated assets,
local backups and the local budget-reference PDF outside Git. Keep source code,
tests, migrations and the placeholder-only .env.example under version control.
Author identity is configured locally for this repository; other repositories
are unaffected. To inspect it, use git config --local user.name and
git config --local user.email.

## Project Layout

- `config/`: Django settings, URLs, WSGI and ASGI entry points.
- `store/`: catalog models, admin, public views, URLs, migrations, and tests.
- `orders/`: session cart, checkout, order models/migration, services, Admin,
  guest confirmation, app templates and tests.
- `core/`: homepage, site settings, and shared contact configuration.
- `accounts/`: customer sign-in, sign-up, sign-out, and authentication tests.
- `repairs/`: repair requests, payments, tracking, notifications, Admin, and tests.
- `templates/`: shared layout, homepage, catalog, product detail, cart, and 404 page.
- `static/`: CSS, minimal JavaScript, and local SVG illustrations/icons.
- `AGENTS.md`: permanent engineering instructions.
- `CAMPUSFRIEND_PLAN.md`: scope, milestones, and business placeholders.
- `.env.example`: configuration reference with no secrets.
- `requirements.txt`: frozen initial dependencies.

## Static Files and Later Deployment

WhiteNoise middleware and compressed manifest static storage are configured.
`manage.py collectstatic --noinput` builds assets into ignored `staticfiles/`.
The development server serves source assets while DEBUG=True.

PostgreSQL configuration and guarded data-transfer commands are ready; follow
[the PostgreSQL operator runbook](POSTGRESQL.md) before connecting a database.
Blank `DATABASE_URL` keeps local SQLite; Render requires a PostgreSQL URL supplied
privately in platform environment settings. The driver uses TLS by default.
Render deployment and Cloudinary storage are not yet configured.
`CLOUDINARY_URL` is currently unused. Paystack
initialization, verification, and signed webhooks are implemented; its public key,
secret key, and live-mode flag are read from the environment. Keep test mode
until live payments are explicitly authorized.

See [pre-deployment readiness](PREDEPLOYMENT.md) for the remaining GitHub/Render
requirements, data preservation steps, and validation commands.

Configuration references:
[Django environment and secret settings](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
and [WhiteNoise's Django integration](https://whitenoise.readthedocs.io/en/stable/django.html).
