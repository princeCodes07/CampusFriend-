# CampusFriend

## Purpose

A mobile-first ecommerce and services application for students at KNUST Campus,
Ghana. The first milestone establishes a working, version-controlled Django
foundation. Business functionality belongs to later milestones.

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

Admin passwords must be entered manually in the local terminal, never recorded
in documentation, source code, .env.example, or Git history.
