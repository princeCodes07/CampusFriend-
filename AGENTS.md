# CampusFriend Engineering Rules

CampusFriend uses a Django monolithic architecture.

## Architecture

- Use Django apps with clear responsibilities.
- Prefer built-in Django functionality.
- Use server-rendered Django templates.
- Use lightweight Vanilla JavaScript.
- Avoid unnecessary packages.
- Avoid premature abstractions.
- Keep business logic outside templates where practical.

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
- This milestone is setup only. Do not implement product/category models, cart,
  checkout, payment integration, order/repair workflows, authentication UI,
  homepage design, product pages, search, or production deployment.
- Never commit secrets, local databases, virtual environments, uploaded media,
  or cache files. Keep source code and migrations in Git.

See CAMPUSFRIEND_PLAN.md for the project scope and milestones.
