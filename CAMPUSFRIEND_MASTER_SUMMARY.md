CAMPUSFRIEND — MASTER ENGINEERING SUMMARY FOR CODEX

Read AGENTS.md and CAMPUSFRIEND_PLAN.md before making changes.

This document supersedes earlier architectural assumptions where they conflict with this direction.

==================================================
1. PRODUCT VISION
==================================================

CampusFriend is not merely an ecommerce website.

CampusFriend is intended to become a student-focused digital ecosystem that helps university students access useful products, services, opportunities, and peer-to-peer resources from one platform.

Long-term ecosystem:

- Store
- Repairs
- Books
- Track Order
- Free Services & Swap
- Innovators

However, development must remain disciplined.

CURRENT PRIORITY:

1. Store
2. Orders / Checkout
3. Track Order
4. Payments
5. Repairs
6. Repair Tracking
7. Books experience refinement

FUTURE:

8. Community / Free Services & Swap
9. Innovators

Do NOT try to build the complete ecosystem at once.

Working core modules take priority over breadth.

==================================================
2. ARCHITECTURAL STYLE
==================================================

CampusFriend should use a:

MODULAR DJANGO MONOLITH

This means:

- one Git repository
- one Django project
- one deployment
- one primary database
- one Django Admin
- multiple Django apps organized by BUSINESS DOMAIN

Do NOT create a separate Django app merely because something appears as a navigation link.

Apps should represent meaningful business capabilities with their own:

- data
- rules
- workflows
- lifecycle
- permissions
- future complexity

Do NOT introduce:

- microservices
- React
- Vue
- Next.js
- Django REST Framework unless genuinely required later
- Redis unless required later
- Celery unless required later
- unnecessary repository/service abstractions
- unnecessary infrastructure

Prefer Django-native solutions.

==================================================
3. TARGET PROJECT STRUCTURE
==================================================

The project should evolve toward:

CampusFriend/
│
├── config/
│   ├── settings/
│   ├── urls.py
│   └── ...
│
├── core/
│   ├── views.py
│   ├── urls.py
│   └── ...
│
├── store/
│   ├── models.py
│   ├── admin.py
│   ├── views.py
│   ├── urls.py
│   ├── catalog.py
│   ├── forms.py
│   ├── tests/
│   └── templates/store/
│
├── orders/
│   ├── models.py
│   ├── cart.py
│   ├── views.py
│   ├── forms.py
│   ├── services.py
│   ├── payments/
│   │   └── paystack.py
│   ├── tests/
│   └── templates/orders/
│
├── repairs/
│   ├── models.py
│   ├── views.py
│   ├── forms.py
│   ├── services.py
│   ├── tests/
│   └── templates/repairs/
│
├── accounts/
│
├── community/          # FUTURE
│   └── Swap / Free services
│
└── innovators/         # FUTURE

IMPORTANT:

This is a TARGET architecture.

Do NOT create empty files, empty applications, or unnecessary abstractions simply to match this tree.

Introduce files such as:

services.py
payments/
forms.py
tests/

when the application actually requires them.

Do not perform a large restructuring of working code without a clear benefit and regression testing.

==================================================
4. DOMAIN OWNERSHIP
==================================================

Each Django app has a clear responsibility.

--------------------------------------------------
CORE
--------------------------------------------------

core owns site-wide concerns.

Examples:

- homepage
- about
- contact
- privacy
- terms
- ecosystem presentation
- general landing pages
- shared site navigation concerns

core must NOT become a dumping ground for business models.

Do NOT place:

Product
Order
RepairRequest
Payment
SwapListing

inside core.

--------------------------------------------------
STORE
--------------------------------------------------

store owns the product catalog.

It includes:

- Category
- Product
- product browsing
- catalog visibility
- product search
- filtering
- sorting
- featured products
- product availability
- related products
- product detail pages

Store categories can include:

- Phone Accessories
- Laptop Accessories
- Audio
- Power
- Electricals
- Smart Devices
- Phones
- Laptops
- Gaming
- Hostel Essentials
- Books
- Study Materials

These are STORE CATEGORIES.

They are NOT separate Django applications.

They should generally come from database content rather than hardcoded empty navigation.

--------------------------------------------------
BOOKS
--------------------------------------------------

Books is a major customer-facing CampusFriend module.

However, Books does NOT currently require its own Django app.

Books should use:

store.Product

with a Books category.

Customer architecture:

CampusFriend
    → Books

Technical architecture:

store.Product
    → category = Books

This allows Books to share:

- stock
- cart
- checkout
- orders
- payments
- pricing
- search
- product cards

Do not duplicate ecommerce functionality.

If Books later requires unique metadata such as:

- ISBN
- Author
- Publisher
- Edition

prefer extending Product through an associated model such as BookDetails rather than building a second commerce engine.

--------------------------------------------------
ORDERS
--------------------------------------------------

orders owns the transactional ecommerce lifecycle.

This includes:

- cart
- checkout
- Order
- OrderItem
- delivery information
- order status
- order tracking
- payment integration
- payment verification

Track Order belongs here.

Do NOT create a separate track_order Django app.

Future architecture:

Track Order
    ↓
Order reference
    ↓
orders domain
    ↓
Order status

--------------------------------------------------
REPAIRS
--------------------------------------------------

repairs owns device repair workflows.

This deserves its own application because its lifecycle is fundamentally different from ecommerce orders.

Future responsibilities:

- RepairRequest
- device details
- customer information
- issue description
- repair reference
- diagnosis
- estimated cost
- customer approval
- repair status
- status history
- repair tracking
- completion

Repairs should NOT be modeled as ordinary store products.

--------------------------------------------------
ACCOUNTS
--------------------------------------------------

accounts owns user identity only when required.

Potential future responsibilities:

- authentication
- profiles
- saved customer information
- order history
- repair history
- saved addresses
- community identity

Do not allow authentication development to delay guest ecommerce checkout.

--------------------------------------------------
COMMUNITY — FUTURE
--------------------------------------------------

community may eventually own:

- free item listings
- free services
- swaps
- peer-to-peer listings
- moderation
- reports
- listing expiry

Possible future model concepts:

Listing
ListingCategory
SwapOffer
Report

Do NOT implement this yet.

--------------------------------------------------
INNOVATORS — FUTURE
--------------------------------------------------

innovators may eventually support:

- InnovatorProfile
- student projects
- startups
- businesses
- portfolios
- project images
- discovery
- collaboration

Do NOT implement this yet.

==================================================
5. CURRENT COMPLETED WORK
==================================================

MILESTONE 1 — SOLID

Current strengths:

- Django configuration is clean
- Django secret is environment-based
- SQLite is used for local development
- WhiteNoise is configured
- templates/static/media are organized
- .gitignore is correct
- secrets are not intentionally committed

Preserve this.

--------------------------------------------------
MILESTONE 2 — SOLID
--------------------------------------------------

Category and Product models are implemented properly.

Important decisions to preserve:

Product.category uses:

on_delete=models.PROTECT

Monetary values use:

DecimalField

Existing catalog strengths include:

- unique SKUs
- unique slugs
- stable slug generation
- non-negative validation
- stock handling
- optional images
- timestamps
- useful Django Admin

Do not weaken these guarantees.

--------------------------------------------------
MILESTONE 3 — COMPLETE
--------------------------------------------------

Existing storefront functionality includes:

- reusable base template
- navbar/footer
- reusable product cards
- homepage
- shop
- categories
- departments
- books
- product details
- search
- sorting
- in-stock filtering
- pagination
- related products
- proper 404 behavior
- accessibility basics
- responsive CSS
- image fallbacks
- empty states

Existing shared catalog visibility logic is good.

Preserve the principle that there should be one consistent definition of a customer-visible product.

--------------------------------------------------
MILESTONE 4 — CART FOUNDATION EXISTS
--------------------------------------------------

The current cart architecture is fundamentally correct.

Session stores:

product ID
quantity

The browser does NOT control:

price
stock
subtotal
availability

Django reloads actual Product records and remains authoritative.

Preserve this security model.

Cart mutations should remain:

- POST-based
- CSRF protected
- server validated

Adding an item to cart must NOT reduce inventory.

==================================================
6. CURRENT PRODUCT DIRECTION
==================================================

CampusFriend should visually communicate that it is an ecosystem.

However, the STORE should currently be the strongest and most functional module.

Primary public navigation should approximately be:

Home
Store
Repairs
Books
Track Order

Also preserve:

Search
Cart

Remove or avoid top-level ecosystem navigation such as:

Laptops
Phones
Electricals
Accessories

Those are store categories.

Do not show empty categories prominently.

Do not display non-functional Sign In controls until authentication actually exists.

==================================================
7. HOMEPAGE DIRECTION
==================================================

The homepage must show substantially more of the actual Store.

It should no longer function primarily as a generic landing page.

Recommended structure:

--------------------------------------------------
A. COMPACT HERO
--------------------------------------------------

Communicate:

CampusFriend is the student ecosystem for products and useful services.

Primary CTA:

Shop CampusFriend

Secondary CTA:

Book a Repair

Keep the hero relatively compact so products appear quickly.

--------------------------------------------------
B. STORE CATEGORIES
--------------------------------------------------

Display active useful product categories dynamically.

Only expose categories that actually contain customer-visible products where practical.

Examples:

Phone Accessories
Audio
Power
Books
Laptop Accessories

Do not create fake inventory.

--------------------------------------------------
C. FEATURED PRODUCTS
--------------------------------------------------

Give this major homepage visibility.

Show approximately 8 products where practical.

Use the existing reusable product card.

Show:

- image
- name
- price
- valid previous price
- stock state
- appropriate action

--------------------------------------------------
D. LATEST PRODUCTS
--------------------------------------------------

Add another real catalog discovery section.

Prefer:

Latest Products

using legitimate created_at data.

Do NOT invent:

- popularity
- sales rankings
- ratings
- trending statistics

unless real data exists.

--------------------------------------------------
E. CAMPUSFRIEND REPAIRS
--------------------------------------------------

Repairs should have a significant homepage section.

Communicate services such as:

- screen repairs
- battery issues
- charging issues
- software problems
- speaker/microphone issues
- gadget diagnosis

Possible CTAs:

Book a Repair
Track Repair

Do not pretend functionality exists if it does not yet exist.

--------------------------------------------------
F. BOOKS
--------------------------------------------------

Show several Book products.

Use the existing Product catalog.

CTA:

Browse Books

--------------------------------------------------
G. TRUST
--------------------------------------------------

Keep trust messaging concise and truthful.

Examples:

- student-focused
- campus convenience
- product support
- repair support
- responsive communication

Do NOT claim secure online payment before payment functionality is actually active.

==================================================
8. STORE MUST BECOME FULLY OPERATIONAL FIRST
==================================================

The development priority now is to complete the Store transaction lifecycle.

Required progression:

Store
    ↓
Cart
    ↓
Checkout
    ↓
Order
    ↓
Order Tracking
    ↓
Payment
    ↓
Delivery

Do not distract development with Community or Innovators yet.

==================================================
9. OLD PRICE BUSINESS RULE
==================================================

Fix and preserve correct old_price semantics.

When old_price exists:

old_price MUST be greater than price.

VALID:

price = 150
old_price = 200

INVALID:

price = 200
old_price = 100

INVALID:

price = 200
old_price = 200

Use Django model validation.

Use a database constraint where appropriate and clean.

The UI should only show a crossed-out price when the previous price is legitimately higher than the current price.

Tests must cover this.

==================================================
10. STOCK SEMANTICS
==================================================

Preserve:

stock=None
    = inventory has not yet been confirmed

stock=0
    = confirmed out of stock

stock>0
    = confirmed available stock

For purchasing:

only stock > 0 is purchasable.

The server is authoritative.

Cart quantity must never exceed confirmed available stock.

Do not deduct stock merely because an item enters the cart.

==================================================
11. NEXT MAJOR MILESTONE — ORDER DOMAIN
==================================================

Before Paystack is introduced, CampusFriend needs a durable Order domain.

Target flow:

Cart
 ↓
Checkout
 ↓
Validate cart again
 ↓
Validate visibility
 ↓
Validate prices
 ↓
Validate stock
 ↓
Create Order
 ↓
Create OrderItems
 ↓
Order status = PENDING
 ↓
Payment comes later

Order should eventually contain concepts such as:

- order number
- customer name
- customer phone
- customer email
- delivery location
- landmark
- delivery notes
- subtotal
- delivery fee
- total
- order status
- payment status
- created_at
- updated_at

Do not finalize exact fields without inspecting current code and business requirements first.

==================================================
12. ORDER ITEM SNAPSHOTS ARE REQUIRED
==================================================

OrderItem must preserve historical purchase information.

Do NOT depend solely on current Product values.

Snapshot at minimum:

- product reference
- product name
- SKU
- unit price
- quantity
- line total

Example:

Customer buys AirPods today for:

GH₵150

Tomorrow Product.price changes to:

GH₵170

The historical order MUST still display:

GH₵150

Never reconstruct old order pricing from the current Product table.

==================================================
13. ORDER CREATION SHOULD BE TRANSACTIONAL
==================================================

When real Order creation is implemented, use Django database transaction handling.

Multi-step operations such as:

create Order
create OrderItems
validate stock
prepare totals

should either:

ALL succeed

or

ALL rollback.

Use transaction.atomic() where appropriate.

Do not hide important business logic inside signals.

==================================================
14. VIEW DESIGN
==================================================

Views should remain reasonably thin.

Preferred pattern:

Request
 ↓
Validate form/input
 ↓
Call domain/business logic
 ↓
Return response

Do NOT let checkout views eventually become several hundred lines of:

- cart calculations
- order creation
- inventory processing
- payment requests
- delivery calculations

When genuine workflow complexity appears, move multi-step logic into:

orders/services.py

But:

DO NOT create service layers prematurely for trivial logic.

==================================================
15. PAYMENTS
==================================================

Payment belongs to the orders domain initially.

Paystack hosted checkout is implemented in test-ready mode. The provider code
lives in `orders/payments.py`; server-rendered views handle guest-session
authorization, while provider requests, verification and payment persistence are
kept outside the view. Each retry has its own unique payment record. Test keys
are the default; live keys are blocked unless explicitly authorized. Real
provider sandbox payments still require configured test keys and a publicly
reachable deployment for webhooks.

Current implementation:

orders/
    payments.py

This module owns:

- Paystack initialization
- Paystack verification
- webhook validation
- provider-specific API communication

Views should not contain large amounts of Paystack-specific HTTP code.

Callbacks do not establish payment success on their own. Callback and signed
webhook paths both verify the transaction with Paystack and match reference,
amount and currency before marking payment paid. Payment status stays separate
from fulfilment status.

==================================================
16. TRACK ORDER
==================================================

Track Order becomes functional after Order exists.

Expected concept:

Customer enters:

Order Number
and possibly another verification value

Server retrieves Order.

Customer sees status.

Possible states later:

PENDING
AWAITING_PAYMENT
PAID
PROCESSING
OUT_FOR_DELIVERY
DELIVERED
CANCELLED

Do not expose sensitive customer/order data through guessable references alone without considering verification/security.

==================================================
17. REPAIRS DIRECTION
==================================================

Once the Store transaction lifecycle is stable, Repairs becomes the next major operational module.

Repairs should eventually support:

RepairRequest

with information such as:

- reference number
- customer
- phone
- email
- device brand
- device model
- issue
- description
- preferred location
- estimated price
- final price
- status
- timestamps

Potential statuses:

RECEIVED
DIAGNOSING
QUOTE_SENT
AWAITING_APPROVAL
REPAIRING
QUALITY_CHECK
READY
OUT_FOR_DELIVERY
COMPLETED
CANCELLED

Exact state design should be reviewed before implementation.

==================================================
18. DJANGO QUERY BEST PRACTICES
==================================================

Preserve reusable catalog query logic.

Avoid duplicating visibility rules throughout different views.

As complexity grows, consider Django-native reusable QuerySets or Managers.

For example, future APIs could conceptually become:

Product.objects.visible()

Product.objects.visible().featured()

Product.objects.visible().in_stock()

Do NOT refactor working catalog.py code just for style.

Only move toward custom QuerySets if it clearly improves maintainability.

==================================================
19. URL STRUCTURE
==================================================

Each domain should own its own URL configuration.

Examples:

store/urls.py
orders/urls.py
repairs/urls.py

Use app namespaces.

Examples conceptually:

store:product_detail
orders:cart
orders:checkout
orders:track
repairs:create
repairs:track

Avoid global ambiguous URL names.

Do not break existing public URLs unnecessarily.

Customer-facing navigation may say:

Store

while the technical URL can temporarily remain:

/shop/

if changing it provides no real benefit.

==================================================
20. TEMPLATE ORGANIZATION
==================================================

Target application-specific templates such as:

store/templates/store/
orders/templates/orders/
repairs/templates/repairs/

Global templates should remain limited to genuinely global content such as:

base.html
shared includes

Do NOT move every working template immediately simply to satisfy directory aesthetics.

Migrate gradually when touching relevant functionality.

==================================================
21. TEST ORGANIZATION
==================================================

Test coverage is already substantial.

As tests continue growing, prefer app-specific test packages.

Example:

store/tests/
    test_models.py
    test_views.py
    test_search.py

orders/tests/
    test_cart.py
    test_models.py
    test_checkout.py
    test_tracking.py

repairs/tests/
    test_models.py
    test_views.py
    test_workflow.py

Do not delete existing tests merely to reorganize them.

Migration to test packages should be safe and incremental.

==================================================
22. SIGNAL POLICY
==================================================

Do NOT use Django signals for critical ecommerce workflows such as:

- order creation
- stock deduction
- payment processing
- status transitions

Important business actions should be explicit and traceable.

Signals may be used later for loosely coupled secondary behavior where appropriate.

==================================================
23. CONFIG / SETTINGS STRUCTURE
==================================================

Target configuration may eventually use:

config/settings/
    base.py
    development.py
    production.py

This can improve separation between local and production configuration.

However:

Do NOT refactor the current working settings.py merely for cosmetic reasons.

Only introduce split settings when production/deployment complexity makes the benefit clear.

If migrating settings:

- preserve existing behavior
- preserve environment variables
- preserve local SQLite
- preserve production PostgreSQL support
- test manage.py
- test WSGI/ASGI configuration
- run complete regression tests

==================================================
24. SECURITY PRINCIPLES
==================================================

Never trust browser values for:

- prices
- totals
- delivery fees
- discounts
- stock
- payment status
- user privileges

Django remains authoritative.

Never commit:

- .env
- Django secret
- Paystack secret
- PostgreSQL credentials
- admin s
- local databases

db.sqlite3 must remain ignored.

==================================================
25. DATA / GIT HYGIENE
==================================================

Before milestone commits run:

git status

Ensure these are not accidentally tracked:

.venv/
.env
db.sqlite3
local uploaded archives
secret keys
credentials

Do not delete the developer's local database merely because it is ignored.

==================================================
26. REQUIRED VALIDATION
==================================================

After meaningful changes always run:

python manage.py check
python manage.py test

Do not claim success if these fail.

For migrations also run:

python manage.py makemigrations --check

where appropriate.

Inspect generated migrations before applying important schema changes.

==================================================
27. CODING PRINCIPLES
==================================================

Follow these consistently:

- prefer Django built-ins
- server-side authority
- explicit business rules
- maintain readable code
- avoid premature abstraction
- avoid unnecessary dependencies
- keep domain ownership clear
- reuse existing functionality
- write tests for important behavior
- preserve working behavior
- do not silently swallow exceptions
- solve root causes rather than symptoms

==================================================
28. CURRENT EXECUTION PRIORITY
==================================================

The implementation order from this point is:

PHASE A — STOREFRONT REFINEMENT

- ecosystem navigation
- Store emphasis
- more homepage products
- stronger Repairs promotion
- remove empty department placeholders
- reduce oversized header
- correct old_price logic
- preserve cart behavior

THEN:

PHASE B — ORDER DOMAIN

- Order model
- OrderItem model
- checkout form
- customer information
- delivery information
- server-calculated totals
- product snapshots
- pending order creation
- transactional order creation

THEN:

PHASE C — TRACK ORDER

- order reference
- secure lookup
- status presentation

THEN:

PHASE D — PAYMENT

- Paystack test-mode initialization, verification, signed webhook and
  idempotent payment state management are implemented.
- Actual Paystack sandbox transactions require test keys and a public webhook
  endpoint. Live keys remain disabled by default.
- Hosted payment methods such as Mobile Money and cards are provided by
  Paystack; the application does not collect card details.

THEN:

PHASE E — REPAIRS

- repair request
- reference number
- repair workflow
- repair admin
- repair tracking

THEN:

PHASE F — ECOSYSTEM EXPANSION

- Community / Free Services & Swap
- Innovators

==================================================
29. IMPORTANT SCOPE RULE
==================================================

CampusFriend's long-term vision is large.

The codebase must not become large merely because the vision is large.

Only add technical complexity when real functionality requires it.

Do not create:

community/
innovators/

until those modules are actually being developed.

Do not create:

payments/
services.py

inside an app before the corresponding workflow genuinely needs them.

The target folder tree communicates ownership and future direction.

It is NOT permission to generate unused boilerplate.

==================================================
30. BEFORE EVERY MAJOR IMPLEMENTATION
==================================================

Before changing code:

1. Read existing implementation.
2. Identify the domain that owns the feature.
3. Reuse existing infrastructure where possible.
4. Explain major architecture changes before performing them.
5. Avoid unrelated refactors.
6. Define the expected behavior.
7. Implement.
8. Test.
9. Report.
10. Stop before Git commit unless explicitly told otherwise.

==================================================
31. FINAL PRODUCT PRINCIPLE
==================================================

CampusFriend should eventually feel like:

ONE CAMPUS ECOSYSTEM

but internally remain:

A SMALL NUMBER OF CLEAN BUSINESS DOMAINS.

Conceptually:

CampusFriend
│
├── Store
│   ├── Products
│   ├── Categories
│   ├── Books
│   └── Cart
│
├── Orders
│   ├── Checkout
│   ├── Payments
│   ├── Delivery
│   └── Track Order
│
├── Repairs
│   ├── Repair Requests
│   └── Repair Tracking
│
├── Community              FUTURE
│   ├── Free Services
│   └── Swap
│
└── Innovators             FUTURE

The Store must become fully operational first.

Do not allow future ecosystem ideas to interfere with completing the current commerce workflow.