# CampusFriend

Django foundation for a mobile-first student ecommerce and services application
at KNUST Campus, Ghana. Milestone 2 adds catalog models and Django Admin
management to the initial foundation.

## Local Setup (Windows PowerShell)

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

Set these environment variables in the same terminal before running Django:

```powershell
$env:DEBUG = 'True'
$env:ALLOWED_HOSTS = '127.0.0.1,localhost,[::1]'
$env:DJANGO_SECRET_KEY = & .\.venv\Scripts\python.exe -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'
```

The generated development key stays in the shell environment and is not written
to source or printed by this assignment. Reuse it for all commands in that
terminal. Generating a new key in a later terminal invalidates existing sessions
and signed links. A future production environment needs a stable, securely
configured key of its own.

`.env.example` documents variable names; **.env files are not loaded
automatically**. If you use an external environment loader, keep its local .env
file ignored. A missing or empty DJANGO_SECRET_KEY causes a clear configuration
error; there is no hardcoded fallback. DEBUG defaults to False, so set it
explicitly for development. SQLite is the only configured database at this stage.

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py check
.\.venv\Scripts\python.exe manage.py test
.\.venv\Scripts\python.exe manage.py runserver
```

Visit http://127.0.0.1:8000/ for a plain setup placeholder and
http://127.0.0.1:8000/admin/ for Django Admin. Stop the server with Ctrl+C.
Catalog model and admin tests run with `manage.py test`. Storefront, cart,
checkout, payments, and repair workflows are not implemented yet.

## Manage the Catalog

Sign in at `/admin/` and open **Store > Categories** or **Store > Products**.
Create a category first, then add products with a unique SKU and a price in GHS.
The product list supports search and category, availability, and featured filters.

- Names and SKUs are required; category names, SKUs, and slugs are unique.
- Slugs are prepopulated in the admin. On ordinary model saves, a blank slug is
  generated from the name with a numeric suffix if needed. Renaming an item
  preserves its slug; edit or clear the slug explicitly to change it.
- Supply unique slugs explicitly for bulk inserts, which bypass model save hooks.
  Database uniqueness is the final guard, including concurrent writes.
- Prices use two decimal places and cannot be negative. Old price is optional;
  no discount relationship between old and current price is required yet.
- Stock is a nonnegative integer, defaulting to zero. `is_in_stock` means
  `stock > 0`; availability and category activity remain separate controls.
- Categories containing products cannot be deleted. Deactivate them or reassign
  their products first.
- Images and descriptions are optional. Uploaded images go into ignored
  `media/products/` and their links work locally with DEBUG=True. Production
  image hosting is deferred to the Cloudinary milestone.

No sample records are seeded into the development database. Tests use a separate
database and temporary image storage.

## Create Your Administrator

After migrating, run this in the terminal with the environment configured:

```powershell
.\.venv\Scripts\python.exe manage.py createsuperuser
```

Supply your chosen `[ADMIN_USERNAME]` and `[ADMIN_EMAIL]`, then enter the password
privately at the hidden terminal prompt. Do not send the password in chat or
store it in documentation, source code, environment examples, or Git.

## Git Identity and GitHub

Set the author name and email for this repository, replacing the placeholders:

```powershell
git config --local user.name 'YOUR NAME'
git config --local user.email 'YOUR VERIFIED EMAIL OR GITHUB NOREPLY EMAIL'
git config --local --get user.name
git config --local --get user.email
```

The author name can be your name; it need not be your GitHub username. For
privacy, copy the exact noreply address displayed in GitHub **Settings > Emails**.
See [GitHub's commit email instructions](https://docs.github.com/en/account-and-profile/how-tos/email-preferences/setting-your-commit-email-address).
These local settings do not change other repositories.

After checks and a review of staged files, the first commit message is
`Initialize CampusFriend Django project`. No remote URL is assumed.
When your GitHub repository exists, replace the URL placeholder before running:

```powershell
git remote add origin '[YOUR_GITHUB_REPOSITORY_URL]'
git remote -v
git push -u origin main
```

## Project Layout

- `config/`: Django settings, URLs, WSGI and ASGI entry points.
- `store/`: catalog models, admin configuration, migrations, and tests.
- `core/`, `accounts/`, `orders/`, `repairs/`: existing app scaffolds.
- `templates/base.html`: basic HTML shell.
- `static/`: CSS, JavaScript, and an image directory placeholder.
- `AGENTS.md`: permanent engineering instructions.
- `CAMPUSFRIEND_PLAN.md`: scope, milestones, and business placeholders.
- `.env.example`: configuration reference with no secrets.
- `requirements.txt`: frozen initial dependencies.

## Static Files and Later Deployment

WhiteNoise middleware and compressed manifest static storage are configured.
`manage.py collectstatic --noinput` builds assets into ignored `staticfiles/`.
The development server serves source assets while DEBUG=True.

Render deployment, PostgreSQL configuration, Cloudinary, and Paystack are future
work. DATABASE_URL, CLOUDINARY_URL, and Paystack variables in .env.example are
reserved and are not consumed by this setup. No deployment is configured.

Configuration references:
[Django environment and secret settings](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/)
and [WhiteNoise's Django integration](https://whitenoise.readthedocs.io/en/stable/django.html).
