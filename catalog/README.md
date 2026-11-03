# Add your real products

Product details live in the database. Every storefront page reads the same
records, so you enter a product once and it can appear in the shop, search,
its category, related products, and the homepage.

`catalog/products.json` contains the 14 Accessories listings and prices supplied
by the owner: four power banks, four AirPods listings, two screen protectors,
and four headphone listings. AirPods 4 is GHS 202 as supplied. Quantities and
photos have not been supplied. `stock: null` shows **Availability to be confirmed**.

## Easiest method: Django Admin

1. Start the app, then open http://127.0.0.1:8000/admin/.
2. Sign in with your administrator account at `/admin/` to manage inventory.
   Customer authentication is not required for the guest cart.
3. Open **Store > Categories > Add category** if your category does not exist.
   Use the names and slugs in the table below.
4. Open **Store > Products > Add product** (direct link:
   http://127.0.0.1:8000/admin/store/product/add/).
5. Enter the actual name, unique SKU, category, price in GHS, and stock count.
   Add short and full descriptions. Include model, condition, compatibility,
   specifications, and what is included where relevant.
6. In **Description and image > Image**, choose your actual product photo.
   Use a clear JPG, PNG, or WebP; around 1000 x 1000 pixels and below 1 MB is a
   useful target. Photos are saved under `media/products/`; do not put them in
   the templates. The admin displays a photo preview after saving.
7. Check **Is available** to publish. Its category must also be active.
   Check **Is featured** to include it among the homepage's first eight
   featured products. Leave stock blank when unconfirmed. Zero means **Out of
   stock**, and a positive quantity means **In stock** and enables **Add to cart**.
8. Save, then use **Open product page** in the Visibility section to review it.

Leave Old price empty unless you have a legitimate previous price to display.
It must be strictly higher than the current price. Clear or raise it when a price
increase would make it equal to or lower than the current price. Use your
own confirmed prices, inventory, and product photos. The existing `DEMO-` SKUs
are samples with illustrative prices and stock; they have been hidden from the
storefront and retained in Admin for reference.
Use a new SKU without the `DEMO-` prefix for a real listing.

## If you want to insert products in a code file

**Edit `catalog/products.json`, inside the `products` list.** This is the one
place prepared for your product entries. Do not insert product data into
`store/models.py`, `store/views.py`, or individual HTML pages.

This is a format example only. Replace every sample value with your own details;
it is deliberately unpublished:

```json
{
  "products": [
    {
      "sku": "YOUR-SKU-001",
      "name": "Your actual product name",
      "category": "accessories",
      "price": "0.00",
      "stock": 0,
      "short_description": "A short, accurate summary of this product.",
      "description": "Actual model, specifications, condition and included items.",
      "is_available": false,
      "is_featured": false
    }
  ]
}
```

Add more objects separated by commas. Use JSON `true`/`false`, not quoted
strings. Prices should be decimal strings such as `"85.00"`; stock must be a
nonnegative whole number or `null` when unconfirmed. Set `is_available` to `true`
only when a listing is ready.
Do not leave the example name or zero price as a real product.

From `Commerce\CampusFriend`, with the environment configured as in the main
README, validate first:

```powershell
.\.venv\Scripts\python.exe manage.py import_products catalog/products.json --dry-run
```

Then save:

```powershell
.\.venv\Scripts\python.exe manage.py import_products catalog/products.json
```

- Required fields: `sku`, `name`, `category`, `price`, `stock`.
- Optional: `old_price` (decimal string or `null`), `short_description`,
  `description`, `is_available`, `is_featured`.
- A new SKU creates a product; an existing SKU updates that product. Re-running
  an import does not duplicate products. A changed SKU is a new product.
- New products default to unpublished if `is_available` is omitted. On updates,
  omitted optional fields keep their existing values. Use `old_price: null` to
  clear an old price.
- Existing product URLs and photos are preserved. Upload or replace photos
  through the Image field in Admin after import.
- A bad entry cancels the whole import. A dry run saves nothing, including
  categories. Duplicate SKUs in one file are rejected.
- Missing recognized categories are created automatically. Existing inactive
  categories stay inactive. Other categories can be created in Admin first.
- Products absent from the file are left alone. To hide one, uncheck **Is
  available** in Admin, or import it with `is_available: false`.
- The file is read only when you run the command. Editing JSON alone does not
  update the website. Later imports overwrite the fields provided in the file,
  including any prices or stock you have since changed in Admin.

## Category names and slugs

| Legacy department | Category name | Exact category slug |
| --- | --- | --- |
| Laptops | Laptops | `laptops` |
| Phones | Phones | `phones` |
| Accessories | Accessories | `accessories` |
| Accessories | Phone Accessories | `phone-accessories` |
| Accessories | Laptop Accessories | `laptop-accessories` |
| Accessories | Audio | `audio` |
| Electricals | Electricals | `electricals` |
| Books & Study Materials | Books | `books` |
| Books & Study Materials | Study Materials | `study-materials` |

Primary navigation is Home, Store, Repairs, Books and Track Order. Category links
within Store and on the homepage come from populated database categories.
Categories must be active and products available to appear publicly. Empty and
hidden-only categories are omitted from discovery links. Legacy department URLs
still work. Category/import definitions live in `store/catalog.py`.

## Where the storefront code is

| File | Purpose |
| --- | --- |
| `catalog/products.json` | Your editable product data for imports |
| `store/models.py` | Product/category field definitions; not individual products |
| `store/admin.py` | The inventory editing screens and photo preview |
| `store/catalog.py` | Category grouping and public visibility rules |
| `store/views.py` | Search, sorting, stock filters, category listings and details |
| `templates/core/home.html` | Homepage layout |
| `templates/store/includes/product_card.html` | A product tile, reused automatically |
| `templates/store/product_list.html` | Shop/category listings and filters |
| `templates/store/product_detail.html` | Full product page and related products |
| `templates/includes/navbar.html` | The shared logo, search and navigation |
| `static/css/style.css` | Appearance and responsive layout |

## Public contact details

Before starting the server, set `BUSINESS_PHONE`, `WHATSAPP_NUMBER`, and
`BUSINESS_EMAIL` to your actual details in the shell environment, for example
`$env:BUSINESS_PHONE = 'your verified business number'`. Restart the server after
changing them. The footer omits empty contact values. `.env.example` lists the
names; `.env` files are not loaded automatically. Do not use placeholder text
as a real contact value.

The guest cart now supports additions, a shared item count, subtotals, and removal.
Only products with confirmed positive stock can be added; adding does not reduce
stock. Checkout, payments, customer accounts, delivery tracking and repair booking
remain later milestones.
