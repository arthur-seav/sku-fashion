# SKU-Fashion

Fashion e-commerce management system — SV34 final project (Advanced Python Programming).

- **Storefront** for customers: browse and filter clothing, pick size/colour variants, cart, coupons, checkout with cash on delivery or bank transfer, order tracking, product reviews.
- **Back-office** for Staff and Admin: catalog with SKU variants, inventory with stock movements, promotions, shipping, order workflow and payment reconciliation, review moderation, reports.

The requirements, use cases and ERD are in `../doc/SKU-Fashion.pdf`.

| | |
|---|---|
| Framework | Django 6.1.2 (Python 3.14) |
| Database | PostgreSQL 17 (Docker) |
| Front end | Django templates, Bootstrap 5.3 themed with the AdminCN design tokens, Geist font, Lucide icons |

---

## 1. Setup

### 1.1 Database (PostgreSQL 17 in Docker)

```bash
docker volume create sku_fashion_pgdata
docker run -d --name sku_fashion_db --restart unless-stopped \
  -e POSTGRES_DB=sku_fashion -e POSTGRES_USER=sku_fashion -e POSTGRES_PASSWORD='<choose-a-password>' \
  -p 127.0.0.1:54321:5432 -v sku_fashion_pgdata:/var/lib/postgresql/data \
  postgres:17
```

Port 54321 is used so it does not clash with another local PostgreSQL. If you have the Docker Compose plugin you can write an equivalent `compose.yaml`; the plain `docker run` above needs nothing extra.

### 1.2 Python environment

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 1.3 Configuration

```bash
cp .env.example .env
```

Edit `.env`:

- `DB_PASSWORD`: the password from step 1.1.
- `DJANGO_SECRET_KEY`: any long random string. You can make one with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.

`.env` is in `.gitignore`. Never commit it.

### 1.4 Create the tables and load the demo data

```bash
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Open <http://127.0.0.1:8000/> for the store and <http://127.0.0.1:8000/backoffice/> for the back-office.

`seed_demo` only runs on an empty database. To start over:

```bash
python manage.py flush --no-input
rm -rf media/products media/receipts
python manage.py seed_demo
```

---

## 2. Demo accounts

Every account uses the password `Demo-Pass-2026`. You can pick a different one with `seed_demo --password "..."`.

| Role | Email | Can do |
|---|---|---|
| Admin | `admin@sku-fashion.local` | Everything, including managing back-office accounts |
| Staff | `staff@sku-fashion.local`, `staff2@sku-fashion.local` | Catalog, inventory, promotions, shipping, orders, reports |
| Customer | `dara@example.com`, `sokha@example.com`, `vibol@example.com`, `channary@example.com`, `rithy@example.com` | Shop, check out, track and cancel own orders, review completed purchases |

### What the demo data contains

- 14 products in 3 top-level categories (Women / Men / Accessories) and their SKU variants. Each product has a real photo from `core/seed_assets/products/<product-slug>.jpg` (extra gallery photos are `<slug>-2.jpg`, `<slug>-3.jpg`, ...); a product without a photo gets a generated placeholder. The photos were collected from the web for this coursework only; replace them with licensed images before making the repo or site public.
- About 10 of the variants are below their safety level or sold out, so the low-stock badge and the stock report have data.
- About 40 orders spread over the last 30 days, in every status. Each one went through the real checkout and workflow services, so stock movements, status history, payments and shipments all match.
- Two fresh bank-transfer orders: one has a receipt waiting to be reconciled, the other is still unpaid.
- Rainy Season Sale campaign: 20% off Dresses and the Light Rain Jacket.
- Coupons: `WELCOME10` (10%, min. $20, once per customer), `FIVEOFF` ($5 off, min. $40) and the expired `SUMMER25`.
- Three shipping methods (Standard, Express, Store pick-up), with cheaper rates for Phnom Penh and Kandal.
- Reviews on about half of the completed items: most are published, the three newest wait in the moderation queue, and one advert was rejected. Dara keeps at least one completed item without a review, so you can write one during the demo.

---

## 3. Scheduled task

Unpaid bank-transfer orders are cancelled after 24 hours (FR-X09). Their stock goes back and their coupon is released. Cash-on-delivery orders are never auto-cancelled. Orders that already have a receipt are also left alone, because they are waiting for Staff, not for the customer.

```bash
python manage.py cancel_unpaid_orders            # cancel now
python manage.py cancel_unpaid_orders --dry-run  # only list what would be cancelled
```

Schedule it hourly with cron, for example:

```
0 * * * *  cd /path/to/program && .venv/bin/python manage.py cancel_unpaid_orders
```

---

## 4. Tests

```bash
python manage.py test
```

There are 142 tests. They include concurrency tests (two buyers competing for the last item) and rollback tests (a checkout that fails partway leaves no trace).

---

## 5. Project structure

Each functional area of the SA document is its own Django app (NFR-07). Business rules live in service classes, and views stay thin.

| App | Covers | Key pieces |
|---|---|---|
| `core` | Shared building blocks | Role permission mixins, back-office CRUD base views, sidebar navigation and badges, `ui` template tags (`icon`, `money`, `tone`), Cambodian provinces, `seed_demo` |
| `accounts` | FR-G/C account functions, UC-01–03, UC-20 | Custom `User` (email login, roles CUSTOMER / STAFF / ADMIN), address book, login lockout after repeated failures, back-office account management |
| `catalog` | Products, UC-04/05, UC-11/12 | Category tree (max. 3 levels), brands, materials, sizes, colours, size charts. Products with images per colour. `VariantGenerator` builds SKUs (`P0012-BLK-M`). Storefront search and filters |
| `inventory` | UC-13, FR-S06/07 | `InventoryService` is the only code that changes stock. Every change writes a `StockMovement` with the resulting balance. Rows are locked against overselling. Low-stock alerts |
| `cart` | UC-06 | Session cart for guests and database cart for members. The guest cart is merged into the member cart at login. Quantities are capped at stock |
| `promotions` | UC-14, FR-S08 | Campaigns (by category/product), coupons (min. spend, total and per-customer limits). `PricingService` picks the best campaign price |
| `shipping` | FR-S09 | Shipping methods, per-province rates, free-shipping threshold. Shipments with carrier and tracking number |
| `orders` | UC-07/08/10, UC-15–17 | `CheckoutService` places the order in one transaction. `OrderWorkflow` allows only permitted status changes and records each one in the history. Back-office order screens |
| `payments` | UC-08, UC-16 | Payment providers (COD, bank transfer). `PaymentService` handles receipt upload, reconciliation and refunds (never more than was paid) |
| `reporting` | UC-19, FR-S10/11 | Dashboard KPIs, sales report by day/month with CSV export, best sellers, stock report |
| `reviews` | UC-22/23, FR-C08, FR-S12 (optional scope) | A customer rates each item of a completed order once. `ReviewService` checks who may write; `ReviewModerationService` approves or rejects with a reason. Only approved reviews and their average appear on the product page |

### Order status flow

```
Pending Payment ──(reconcile)──▶ Paid ──▶ Preparing ──(create shipment)──▶ Shipped ──▶ Completed
       │                          │           │
       └──────────────────────────┴───────────┴──▶ Cancelled  (stock restored, coupon released)
```

- **COD** orders start at *Preparing*. Their payment is marked paid when the order is completed.
- **Bank transfer** orders start at *Pending Payment*. They move to *Paid* only when Staff confirm the uploaded receipt.
- **Shipped** orders cannot be cancelled. Returns are outside the scope of this release.

### URLs

| Path | |
|---|---|
| `/` | Storefront home |
| `/shop/` | Product list, filters, product pages |
| `/cart/`, `/orders/checkout/` | Cart and checkout |
| `/orders/` | Customer's own orders |
| `/account/` | Login, register, profile, addresses |
| `/account/reviews/` | Customer's reviews and items waiting for one |
| `/backoffice/` | Back-office dashboard and reports |
| `/backoffice/{catalog,inventory,promotions,shipping,orders,reviews,accounts}/` | Back-office modules |
| `/django-admin/` | Django admin, for superusers debugging only |

---

## 6. Differences from the SA document

These were decided during implementation. Each one is either needed by the code or fills a gap in the ERD.

- `created_at` was added to `OrderStatusHistory`, `StockMovement`, `Refund` and `CouponRedemption` so records can be audited.
- `StockMovement` also stores `balance_after` and a `reference` (the order number or `MANUAL`).
- A shipment only has the states *Shipped* and *Delivered*. Marking it delivered does not complete the order; Staff complete it.
- Store pick-up is a shipping method with a fee of 0.
- VAT (10%) is charged on the subtotal after discounts.
- FR-X09 auto-cancel skips bank-transfer orders whose customer has already uploaded a receipt. Those customers have paid; cancelling them would leave money without an order.
- `Review` adds `submitted_at`, `moderated_by`, `moderated_at` and `moderation_note` to the ERD's four fields. The note is the reason for a rejection, and the customer sees it.
- FR-C08 says each purchased item is reviewed "once". Here that means one review per order item: the customer can edit it while it is pending or rejected (it goes back to the queue), but not after it is published. Buying the same product again in a new order allows a new review.
- Staff can unpublish an approved review by rejecting it with a reason.

---

## 7. Credits

- Back-office design follows [AdminCN](https://themewagon.com/themes/admincn/) by [shadcn/studio](https://shadcnstudio.com/) (MIT). Its design tokens and layout were re-implemented in CSS for Bootstrap. No React code was used.
- [Bootstrap](https://getbootstrap.com/) 5.3.8 (MIT).
- [Geist](https://vercel.com/font) font (SIL OFL 1.1): `static/vendor/geist/OFL.txt`.
- [Lucide](https://lucide.dev/) icons (ISC): `static/vendor/lucide/LICENSE`.
