# Automatic delivery locations (supersedes admin-managed zones)

The owner replaced Delivery Pricing V1 with this fixed checkout policy on
2026-10-13. There is no DeliveryZone model, table, foreign key or admin screen.
Migration history is retained so existing installations can upgrade safely.

## Fixed choices and online charges

| Select location | Delivery included online |
| --- | --- |
| Campus | GHS 0.00 (free) |
| Pickup (Palms Eatery) | GHS 0.00 |
| Ayeduase | GHS 10.00 |
| Kotei | GHS 10.00 |
| Boadi | GHS 10.00 |
| Newsite | GHS 10.00 |
| Other location | No delivery charge collected online; arranged separately |

`orders/delivery.py` is the authoritative, hardcoded policy. All new orders
proceed to `AWAITING_PAYMENT` automatically, with no admin approval. Delivery
fees are added to the items subtotal on the server using Decimal arithmetic.
Other location is payable for items only; checkout, confirmation and order
history clearly state that delivery is discussed, agreed and paid separately.
It is not advertised as free delivery and no delivery price is shown for it.

The single location selector replaces the old delivery-method/zone selectors.
Address, landmark and notes remain separate. Address and landmark are required
for delivery and optional for pickup. Unknown or missing locations are rejected;
posted fees, totals, legacy zone IDs and delivery methods cannot override pricing.
Guest checkout and session ownership remain unchanged.

## Migration and historical orders

Run `python manage.py migrate` with the project's virtual environment.
`0005_fixed_delivery_locations` adds the selected location code, renames the
saved location label, preserves any missing historical labels from their old
zone record, and removes the zone foreign key and table. It does not reprice
existing orders or alter payment/fulfilment statuses. Back up the database before
migration; removed zone configuration cannot be reconstructed by reversing the
schema migration alone.

Existing manually quoted orders keep the legacy admin quote action. New fixed
location orders do not expose it. Paid pricing is immutable; legacy unpaid quote
changes permanently invalidate old payment references, including if the fee is
later reverted. Historical order names and fees are snapshots, unaffected by a
future code change to the delivery policy.

## Payments and verification

Paystack remains in test mode unless live mode is explicitly authorized. The
backend still checks inventory and verifies amount, currency and reference.
Callbacks use server verification, webhooks retain HMAC-SHA512 verification,
and duplicate successful events remain idempotent. Payment and fulfilment states
stay separate. No automatic delivery-fee collection, refund, stock reservation,
or fulfilment change is introduced for Other location.

Tests mock provider requests and cover all seven locations, correct initialization
amounts, Other-location messaging before/after payment, invalid choices, historical
quotes, paid-order immutability, stale references and preservation during zone
removal. No real Paystack sandbox end-to-end transaction is claimed.

Run from CampusFriend with process-local development settings:

```powershell
$env:DEBUG='True'
.\.venv\Scripts\python.exe manage.py test orders
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py makemigrations --check
```

Production launch still requires a real sandbox transaction and public HTTPS
webhook verification. Other-location delivery must be coordinated directly with
the customer; the items-paid status does not mean its delivery fee is settled.

## Completion report (2026-10-13)

The original Quote pending behavior came from order creation requiring the
manual quote-confirmation transition before payment eligibility. New orders now
run that existing transition automatically with the server's fixed fee. Existing
pending orders retain their historical quote workflow and are not repriced.

Migration `0005_fixed_delivery_locations` was applied locally after creating
`db.before-fixed-locations.20261013.sqlite3`. Verification confirmed that all 8
orders, 10 order items, 1 payment and 8 status-history entries were preserved,
including pricing and payment state, and that the delivery-zone table was removed.
No admin location setup or approval is required for new orders.

Validation results:

- Orders suite: 119 tests passed.
- Full suite: 258 tests passed, including Repairs regression coverage.
- Django system check: no issues.
- Migration consistency check: no changes detected.
- JavaScript syntax check: passed.
- Running local checkout: HTTP 200; all seven fixed choices present and the zone
  selector absent. A disposable cart was added and emptied; no order was submitted.
- Paystack requests in tests were mocked; no real sandbox transaction occurred.

Files changed for the fixed-location replacement and zone removal:

```text
.env.example
README.md
DELIVERY_PRICING_V1.md
config/settings.py
orders/delivery.py
orders/models.py
orders/forms.py
orders/services.py
orders/views.py
orders/admin.py
orders/migrations/0005_fixed_delivery_locations.py
orders/test_checkout.py
orders/test_delivery_pricing.py
orders/templates/orders/checkout.html
orders/templates/orders/confirmation.html
orders/templates/orders/order_list.html
orders/templates/orders/includes/totals.html
orders/templates/admin/orders/order/quote.html
static/js/main.js
```

## Order summary presentation update (2026-10-13)

The checkout previously rendered seven price sections and relied on JavaScript
to hide the unused ones; its script cache version had also stayed unchanged.
It now renders one summary, updated from server-calculated JSON for the selected
location. An unselected location shows a prompt instead of an assumed final total.
Validation errors preserve the selected location and its correct total. Other
location hides the delivery price and explains the separate arrangement.

The saved order now puts its summary and payment action before order status,
payment status, tracking and item details in both document and visual order.
Continue shopping is a secondary link. CSS and JavaScript asset versions were
updated so browsers request the current files.

Changed files: `orders/views.py`, `orders/forms.py`,
`orders/templates/orders/checkout.html`,
`orders/templates/orders/confirmation.html`, `orders/test_delivery_pricing.py`,
`static/js/main.js`, `static/css/style.css`, `templates/base.html`, and this report.
No migration or payment-provider changes were required.

Validation: 122 Orders tests and 261 full-project tests passed; Django checks,
migration consistency and JavaScript syntax checks passed. Headless Edge checks
covered all seven choices at 390px, 768px and 1280px, including payment-before-status
layout and no horizontal overflow. Mobile and desktop screenshots were inspected.
The live local checkout was also checked with scripts disabled: one summary,
no assumed delivery price and a fallback explanation. UI order fixtures used an
isolated in-memory database; no provider transaction was initiated.
