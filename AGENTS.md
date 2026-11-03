# CampusFriend Engineering Rules

CampusFriend uses a modular Django monolith organized by business domain.
Read CAMPUSFRIEND_PLAN.md and CAMPUSFRIEND_MASTER_SUMMARY.md before changes.
The owner's master summary supersedes conflicting earlier architectural assumptions.

## Architecture

- Use Django apps with clear responsibilities.
- Prefer built-in Django functionality.
- Use server-rendered Django templates.
- Use lightweight Vanilla JavaScript.
- Avoid unnecessary packages.
- Avoid premature abstractions.
- Keep business logic outside templates where practical.
- Store owns the catalog, including Books. Orders owns cart, checkout, orders,
  tracking and payments. Repairs owns its distinct service workflow. Core owns
  site-wide presentation. Do not create an app for each navigation link.
- Treat the master summary's directory tree as a target, not scaffolding work.
  Add services, payments modules, test packages or split settings only when needed.
- Never put critical order, stock, payment or status workflows in signals.

## Ecommerce Security

Never trust values coming from the browser for:

- Product prices
- Cart totals
- Discounts
- Delivery fees
- Stock
- User permissions
- Payment status

The Django backend must calculate or validate them.

## Secrets

Never hardcode:

- API secrets
- Database credentials
- Django secret keys
- Payment secrets

Use environment variables.

## Payments

- Payment initialization must occur server-side.
- Payment success must be verified server-side.
- Paystack callbacks alone must not be treated as final payment confirmation.
- Support Paystack transaction verification and webhooks.
- Payment processing should be idempotent.
- Use Paystack test mode until live payments are explicitly authorized.

## Development

Before changing architecture:

1. Inspect existing code.
2. Explain the reason for the change.
3. Prefer the smallest safe implementation.

After implementing functionality:

- Run Django checks.
- Run available tests.
- Inspect relevant errors.
- Fix root causes.

Do not hide errors.

## Interface

CampusFriend is mobile-first. Optimize primarily for:

- Smartphones
- Simple navigation
- Quick checkout
- Low-bandwidth connections
- Clear calls to action

## Priority

Working software is more important than unnecessary complexity.

## Stack and Current Scope

- Use Python, Django 5.2 LTS, Django Templates, HTML, CSS, and Vanilla JavaScript.
- Use SQLite locally; PostgreSQL and Render are planned for production.
- Use Django Admin and WhiteNoise; Paystack and Cloudinary integrations come later.
- Do not introduce React, Vue, Next.js, Django REST Framework, Docker, Redis,
  Celery, or microservices without explicit user instruction.
- Milestones 1–3 are complete and the Milestone 4 guest cart foundation exists.
- Completed Phase A refined the storefront: ecosystem navigation, compact header
  and hero, populated category links, featured/latest products, repair promotion,
  and previous-price validation. Preserve the cart, colors and public URLs.
- Main navigation is Home, Store, Repairs, Books, Track Order, with search and
  cart. Product categories belong inside Store; omit empty discovery links and
  non-functional Sign In controls.
- A previous price must be strictly greater than the current price. Enforce this
  through model validation, a database constraint, and display guards.
- Use available products in active categories consistently across public pages.
  Out-of-stock products may remain visible with clear status labels.
- The user has authorized the first cart step after storefront review:
  session-based Add to cart, a shared quantity count, and a cart summary with
  removal. Calculate prices/totals from the catalog and validate current stock.
- Current Phase B is the durable Order/OrderItem domain and guest checkout;
  C is secure order tracking; D is verified Paystack test payments; E is repairs.
  Community and Innovators remain future work. Do not build all phases at once.
- Phase B includes guest checkout, transactional order requests, immutable item
  snapshots, session-restricted confirmation, and Admin delivery quote confirmation.
- The owner's checkout delivery note overrides earlier pending-order assumptions.
  Start at QUOTE_PENDING. The intended flow is QUOTE_PENDING -> AWAITING_PAYMENT
  -> PAID -> PROCESSING -> OUT_FOR_DELIVERY -> DELIVERED. Only the quote-confirmation
  transition is enabled now; payment status is separate and remains UNPAID.
- Collect name, required phone, optional email, delivery method, campus location,
  landmark and optional notes. Location/landmark are required for campus delivery
  and optional for pickup. Pickup has a Decimal 0.00 delivery fee.
- Calculate subtotal using current database prices and Decimal arithmetic.
  Unknown delivery_fee and total are SQL NULL; "To be confirmed" is UI text only.
  The server always derives total = subtotal + delivery_fee when fee is known.
  Admin may confirm the fee through the dedicated action but cannot set total.
- Revalidate visibility, prices, stock and requested quantities before saving.
  Snapshot product reference, name, SKU, unit price, quantity and line total.
  Use a unique checkout token plus transactions for server-side duplicate protection.
- Pending orders never reserve/decrement stock. Validate stock again before future
  Paystack initialization. No payment integration, repair booking, authentication
  or deployment in Phase B. Secure independent tracking is Phase C.
- Do not introduce frontend frameworks or external search services.
- Leave storefront and cart changes uncommitted for user review.
- Never commit secrets, local databases, virtual environments, uploaded media,
  or cache files. Keep source code and migrations in Git.

See CAMPUSFRIEND_PLAN.md for the project scope and milestones.
