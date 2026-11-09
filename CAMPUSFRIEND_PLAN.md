# CampusFriend

The owner's [master engineering summary](CAMPUSFRIEND_MASTER_SUMMARY.md) is the
current direction and supersedes conflicting earlier milestone assumptions below.

## Purpose

A mobile-first ecosystem for students at KNUST Campus, Ghana. Complete the Store
transaction lifecycle first, then Repairs. Community, Free Services & Swap, and
Innovators are future modules, not applications to scaffold now.

## Current Roadmap

- **Phase A — Storefront refinement:** Home, Store, Repairs, Books, Track Order
  navigation; search and cart; a compact header/hero; populated category links;
  up to eight featured products, eight latest products by created_at, and four
  Books/Study Materials products when available. Promote planned repair support
  honestly. Remove the non-functional Sign In control. Keep existing colors.
- Require `old_price > price` whenever old_price is supplied. Use model
  validation, a database constraint, and defensive rendering. Preserve stock
  semantics: null is unconfirmed, zero is sold out, positive is purchasable.
- **Phase B — Orders and guest checkout:** inspect business requirements before
  finalizing Order/OrderItem fields. Revalidate the cart, snapshot names/SKUs/
  prices/quantities/totals, and create pending orders transactionally. The server
  calculates all totals. Authentication must not delay guest checkout.
- **Phase C — Track Order:** secure lookup and status presentation within orders;
  do not expose customer information through guessable references alone.
- **Phase D — Payments:** Paystack hosted checkout, server verification, signed
  webhooks and idempotent payment updates are implemented. Keep test keys as the
  default; live keys remain blocked unless explicitly authorized.
- **Phase E — Repairs:** a separate request/diagnosis/approval/repair/tracking
  lifecycle in repairs, with its state design reviewed before implementation.
- **Phase F — Future ecosystem:** Community/Free Services & Swap, then Innovators.

Keep one repository, Django project, primary database, Admin and deployment.
Categories and Books stay in store; transactions and tracking stay in orders.
Preserve working URLs, templates, test coverage and settings. Introduce new
structure only for a clear functional need. No Git commit without instruction.

## Phase B: Checkout Delivery Rules (2026-10-01)

The owner's checkout delivery note supersedes earlier order/fee assumptions.
Phase A is complete. Phase B adds guest checkout and durable orders, with these rules:

- Collect customer name, required phone, optional email, delivery method, campus
  location / hall / hostel, landmark and optional delivery notes. For pickup,
  location and landmark may be blank; do not invent a collection point.
- The backend revalidates visibility, current prices, stock and quantities before
  saving an order and its items in one transaction. Snapshots contain product
  reference, product name, SKU, unit price, quantity and line total.
- Subtotal is a server-calculated Decimal. Campus delivery fee and final total
  are NULL until confirmed; show "To be confirmed" only in the UI. Pickup fee is
  Decimal 0.00. A flat campus fee can only be configured if approved by the owner.
- Total is always derived on the server: subtotal + delivery_fee. Neither the
  browser nor Admin can independently set it. Admin has a dedicated fee-confirmation
  action; order details and item snapshots are otherwise read-only.
- New requests are QUOTE_PENDING / UNPAID, including pickup while arrangements
  await confirmation. Admin fee confirmation moves them to AWAITING_PAYMENT.
  Full intended order flow: QUOTE_PENDING -> AWAITING_PAYMENT -> PAID -> PROCESSING
  -> OUT_FOR_DELIVERY -> DELIVERED. Later transitions belong to future milestones;
  payment status remains separate from order status.
- Use an unguessable reference and session-restricted confirmation. Duplicate
  submission protection uses a unique database token and transactional writes,
  independent of JavaScript. Changed previews require customer review again.
- Pending orders never reserve or decrement stock. Validate stock again before
  future Paystack payment initialization. Paystack remains out of this milestone.

Phase C (secure order lookup and tracking) follows review of this checkout flow.

The original milestones below record earlier acceptance criteria. Phase A
supersedes the earlier category-only primary navigation and disabled-cart UI.

## Product Scope for Later Milestones

- Phone and laptop accessories, chargers, cables, power banks, earphones,
  headsets, smart watches, phone cases, and screen protectors.
- Personal-development books.
- Campus delivery and order tracking.
- Phone and gadget repair requests and repair tracking.
- Ghana Mobile Money and card payments through Paystack.

## Priorities

1. Working application
2. Clean architecture
3. Secure ecommerce functionality
4. Mobile-first user experience
5. Maintainable code
6. Professional visual design
7. Deployment readiness

Avoid unnecessary complexity.

## Technology

Python, Django 5.2 LTS, Django Templates, HTML5, CSS3, Vanilla JavaScript,
SQLite locally, PostgreSQL for production, Django Admin, Paystack, WhiteNoise,
Git, GitHub, and Render. Cloudinary product images will come later.

Initial dependencies: Django >=5.2,<5.3, Pillow, requests, whitenoise,
dj-database-url, and psycopg[binary]. Exact installed versions are recorded in
requirements.txt. PostgreSQL configuration and all service integrations are
deferred.

Do not introduce React, Vue, Next.js, Django REST Framework, Docker, Redis,
Celery, or microservices unless explicitly requested.

## Application Responsibilities

| App | Responsibility |
| --- | --- |
| core | Homepage, informational pages, shared site functionality |
| accounts | Customer authentication and profiles later |
| store | Products, categories, browsing, inventory, storefront |
| orders | Cart, checkout, orders, payments, delivery, tracking |
| repairs | Repair requests, tracking, repair workflow |

## Setup Milestone Acceptance Criteria

- Initialize Git on main and protect secrets and generated files with .gitignore.
- Record permanent engineering rules in AGENTS.md.
- Create .venv, install the initial dependencies, and freeze requirements.txt.
- Create config and the five Django apps in the repository root.
- Register the apps, configure root templates and static directories, and add
  basic base.html, style.css, and main.js files.
- Provide .env.example with empty secret placeholders.
- Use a local SQLite database and run built-in migrations.
- Pass Django system checks and run any available tests.
- Start the development server and verify an HTTP response at 127.0.0.1:8000.
- Make Django's administrator creation command available; the developer must
  choose their username/email and enter the password locally and privately.
- Review source and staged files, then commit with the message
  "Initialize CampusFriend Django project".
- Configure a GitHub remote and push main only when the actual URL is supplied.

During Milestone 1, do not implement product/category models, cart, checkout,
Paystack integration, orders, repair workflows, authentication UI, homepage
design, product pages, search, or production deployment.

## Milestone 2: Catalog Models and Django Admin

Keep the existing project structure. Add Category and Product in the store app
and make both manageable in Django Admin.

- Category: unique name and slug, description, active flag, and timestamps.
- Product: protected category relationship, name, unique slug and SKU,
  descriptions, decimal price and nullable old price, integer stock, optional
  image, availability/featured flags, and timestamps.
- Reject negative prices and stock through validation and database constraints.
- Generate missing slugs on ordinary saves, handle existing slug collisions,
  preserve supplied slugs, and keep slugs stable when names change.
- Provide useful string representations, name ordering, and an is_in_stock helper.
- Add admin columns, search, filters, slug prepopulation, and category selection.
- Create and inspect migrations, migrate locally, and run Django checks/tests.
- Use isolated test data; do not introduce a fixture system or hardcoded products.
- Do not implement cart, orders, checkout, payments, repair workflows, or
  homepage design. Do not commit until the user reviews the result.

## Milestone 3: Storefront MVP

Preserve the existing architecture and catalog models. Use Django templates,
maintainable mobile-first CSS, and lightweight Vanilla JavaScript.

- Shared base template, navbar, footer, message area, metadata, and product card.
- Homepage with a campus essentials hero, active categories, up to eight visible
  featured products, campus delivery and repairs promotions, and trust messaging.
- Shop and category pages with 12 products per page. Search name, descriptions,
  and SKU with Django ORM; preserve the query during pagination.
- `/books/` uses Product and the active category identified by
  `BOOKS_CATEGORY_SLUG` (default `books`), then the name Books as a fallback.
- Product detail shows price, stock, descriptions, SKU, and optional imagery.
  Quantity and cart controls remain disabled with a clear coming-soon message.
- Public visibility requires product availability and an active category.
  Invalid or hidden products/categories return 404. Zero stock remains visible.
- Professional repairs and order tracking placeholders; no fake workflows.
- Responsive layouts, keyboard access, visible focus, labelled controls,
  meaningful empty states, and local vector placeholders for missing images.
- Test existing and new behavior, inspect at mobile/tablet/desktop widths, and
  verify the development server. Report any local sample data created.
- Do not implement cart, checkout, payments, orders, delivery calculations,
  repair booking, authentication UI, Cloudinary integration, or deployment.
- Stop before committing and report the changes and verification results.

### Storefront review refinements

- Keep the existing colors and the search-led header approved during review.
  Navigation: Laptops, Phones, Accessories, Electricals, Books & Study Materials,
  Repairs, and Track order. These are catalog destinations; real inventory is
  supplied by the owner.
- Support sorting, in-stock filtering, and related products. Include the
  `study-materials` category alongside Books.
- Manage actual products and photos in Django Admin. An optional, validated
  `catalog/products.json` import supports editing product data in a file.
  Do not invent sale prices, stock counts, specifications, or product photos.
- Clearly label the existing demo listings. Customer sign in, ordering,
  payments, delivery and repair workflows remain later milestones.
- Configure verified contact details through environment variables and omit
  empty details from customer pages.
- The owner supplied 14 Accessories product names and GHS prices. Unknown
  quantities are stored as null and shown as Availability to be confirmed;
  zero is reserved for confirmed out-of-stock items. Product photos and exact
  specifications remain owner-supplied content.

## Milestone 4: Cart — first step

Authorized after the storefront and product-image review. This supersedes the
disabled-cart restriction in Milestone 3; checkout and order placement remain
future work.

- Add visible, in-stock products from shop cards and product pages without login.
- Keep product IDs and quantities in the visitor's Django session. The header
  badge counts units, including repeated additions of the same product.
- Provide a cart page with product images, quantities, current prices, decimal
  subtotals, item removal, an empty state, and a continue-shopping link.
- Validate quantities and cumulative stock on the server. Reject hidden,
  inactive-category, out-of-stock, and stock-unconfirmed products.
- Use current database prices. Refresh saved carts against stock and visibility
  changes and explain adjustments to the customer.
- Require POST and CSRF for additions/removals. Adding never reserves or reduces
  stock and never creates an order or payment.
- Preserve the existing colors and header layout. Keep changes uncommitted for
  review. Quantity editing, checkout, delivery fees, orders and payments follow.

## Configuration and Secrets

Use environment variables for secrets. Never commit .env files, credentials,
API keys, virtual environments, SQLite databases, uploaded media, or caches.
The placeholder-only .env.example is intentionally tracked.

DJANGO_SECRET_KEY, DEBUG, and ALLOWED_HOSTS configure the initial application.
DATABASE_URL, PAYSTACK_PUBLIC_KEY, PAYSTACK_SECRET_KEY, and CLOUDINARY_URL are
reserved for later integrations. Never use real Paystack keys in source code;
start with test mode when payments are implemented.

Payment initialization and verification must occur server-side. Callbacks alone
must never confirm a payment. Implement verified webhooks, transaction
verification, and idempotent processing in the payment milestone. The backend
must calculate/validate prices, totals, discounts, fees, stock, permissions,
and payment status.

## Project Information

| Item | Value |
| --- | --- |
| Business | CampusFriend |
| Primary location | KNUST Campus, Ghana |
| Repair location | [REPAIR_LOCATION] |
| Business phone | [BUSINESS_PHONE] |
| WhatsApp | [WHATSAPP_NUMBER] |
| Business email | [BUSINESS_EMAIL] |
| Instagram | [INSTAGRAM_URL] |
| TikTok | [TIKTOK_URL] |
| X / Twitter | [X_URL] |
| Facebook | [FACEBOOK_URL] |
| Website/domain | [DOMAIN_NAME] |
| GitHub username | [YOUR_GITHUB_USERNAME] |
| GitHub repository | [YOUR_GITHUB_REPOSITORY_URL] |
| Suggested repository name | campusfriend |
| Production host | Render |
| Production database | PostgreSQL |
| Production URL | [RENDER_URL] |
| Custom domain | [CUSTOM_DOMAIN] |
| Admin username | [ADMIN_USERNAME] |
| Admin email | [ADMIN_EMAIL] |

Admin s must be entered manually in the local terminal, never recorded
in documentation, source code, .env.example, or Git history.
