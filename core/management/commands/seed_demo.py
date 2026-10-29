"""Load demo data for presentations: accounts, catalog with images and stock,
shipping, promotions and ~30 days of orders in various states.

Everything is created through the same services the application uses, so
stock movements, status history and coupon redemptions are all consistent.

    python manage.py seed_demo            # on an empty database
    python manage.py seed_demo --password "Something-Else-1"
"""

import random
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.contrib.sessions.backends.db import SessionStore
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import RequestFactory
from django.utils import timezone
from PIL import Image, ImageDraw, ImageFont

from accounts.models import Address, User
from cart.services import CartService
from catalog.models import (Brand, Category, Color, Material, Product, ProductImage, ProductVariant, Size,
                            SizeChart)
from catalog.services import VariantGenerator
from inventory.services import InventoryService
from orders.models import Order, OrderItem, OrderStatus
from reviews.models import Review
from reviews.services import ReviewModerationService, ReviewService
from orders.services import CheckoutService
from orders.workflow import OrderWorkflow
from payments.services import PaymentService
from promotions.models import Campaign, Coupon, DiscountType
from shipping.models import ShippingMethod, ShippingRate
from shipping.services import ShipmentService

COLORS = [("Black", "#1F1F1F"), ("White", "#F5F5F2"), ("Navy", "#1F2A44"), ("Beige", "#D8C8A8"),
          ("Olive", "#6B6B3A"), ("Terracotta", "#C0603F"), ("Sky Blue", "#8DB8DD")]
SIZES = ["XS", "S", "M", "L", "XL", "28", "30", "32", "34"]

# (name, category, brand, price, materials, colors, sizes, description)
PRODUCTS = [
    ("Everyday Cotton Tee", "Women Tops", "Tonle Basics", "12.00", ["Cotton"], ["White", "Black", "Sky Blue"],
     ["XS", "S", "M", "L"], "A soft, breathable crew-neck tee for hot days."),
    ("Linen Button Blouse", "Women Tops", "Kampot Linen", "28.00", ["Linen"], ["White", "Beige"],
     ["S", "M", "L"], "Relaxed linen blouse with mother-of-pearl buttons."),
    ("Silk Camisole", "Women Tops", "Angkor Atelier", "35.00", ["Silk"], ["Black", "Terracotta"],
     ["XS", "S", "M"], "Bias-cut silk camisole with adjustable straps."),
    ("Wrap Midi Dress", "Dresses", "Angkor Atelier", "48.00", ["Polyester"], ["Navy", "Terracotta", "Olive"],
     ["S", "M", "L"], "Flowing wrap dress that works from office to dinner."),
    ("Linen Shirt Dress", "Dresses", "Kampot Linen", "52.00", ["Linen"], ["Beige", "White"],
     ["S", "M", "L", "XL"], "Belted shirt dress in washed linen."),
    ("High-Rise Straight Jeans", "Women Bottoms", "Mekong Denim", "45.00", ["Denim", "Cotton"], ["Navy", "Black"],
     ["28", "30", "32"], "Rigid denim with a straight leg and high rise."),
    ("Pleated Wide Trousers", "Women Bottoms", "Angkor Atelier", "39.00", ["Polyester"], ["Black", "Beige"],
     ["S", "M", "L"], "Fluid wide-leg trousers with front pleats."),
    ("Oxford Shirt", "Men Shirts", "Tonle Basics", "26.00", ["Cotton"], ["White", "Sky Blue"],
     ["S", "M", "L", "XL"], "Classic button-down oxford shirt."),
    ("Linen Camp Shirt", "Men Shirts", "Kampot Linen", "32.00", ["Linen"], ["Olive", "Beige", "White"],
     ["M", "L", "XL"], "Short-sleeve camp-collar shirt in pure linen."),
    ("Slim Chinos", "Men Pants", "Tonle Basics", "34.00", ["Cotton"], ["Beige", "Navy", "Olive"],
     ["30", "32", "34"], "Stretch-cotton chinos with a slim taper."),
    ("Selvedge Denim", "Men Pants", "Mekong Denim", "68.00", ["Denim"], ["Navy"],
     ["30", "32", "34"], "14oz selvedge denim, raw finish."),
    ("Denim Trucker Jacket", "Outerwear", "Mekong Denim", "75.00", ["Denim"], ["Navy", "Black"],
     ["M", "L", "XL"], "Four-pocket trucker jacket."),
    ("Light Rain Jacket", "Outerwear", "Tonle Basics", "55.00", ["Polyester"], ["Olive", "Black"],
     ["S", "M", "L", "XL"], "Packable shell for the rainy season."),
    ("Woven Tote Bag", "Bags", "Angkor Atelier", "24.00", ["Cotton"], ["Beige", "Black"],
     ["M"], "Hand-woven tote with leather handles."),
]


def placeholder_image(name, hex_color, filename):
    """A simple product picture: the color as background with the product name."""
    img = Image.new("RGB", (600, 800), hex_color)
    draw = ImageDraw.Draw(img)
    rgb = img.getpixel((0, 0))
    ink = (20, 20, 20) if sum(rgb) > 380 else (245, 245, 245)
    try:
        font = ImageFont.load_default(size=42)
    except TypeError:
        font = ImageFont.load_default()
    words, lines, line = name.split(), [], ""
    for w in words:
        if len(line + " " + w) > 14:
            lines.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    lines.append(line)
    y = 320
    for text in lines:
        width = draw.textlength(text, font=font)
        draw.text(((600 - width) / 2, y), text, fill=ink, font=font)
        y += 56
    draw.rectangle([40, 40, 560, 760], outline=ink, width=3)
    buf = BytesIO()
    img.save(buf, "PNG")
    return ContentFile(buf.getvalue(), name=filename)


class Command(BaseCommand):
    help = "Populate an empty database with demo data for SKU-Fashion."

    def add_arguments(self, parser):
        parser.add_argument("--password", default="Demo-Pass-2026", help="Password for every demo account.")
        parser.add_argument("--seed", type=int, default=34, help="Random seed (same data every run).")

    def handle(self, *args, password, seed, **options):
        if Product.objects.exists() or Order.objects.exists():
            raise CommandError("The database already has catalog or order data. Run `python manage.py flush` "
                               "first if you want a fresh demo database.")
        random.seed(seed)
        with transaction.atomic():
            users = self.accounts(password)
            self.catalog(users["staff"])
            self.shipping()
            self.promotions()
        self.orders(users)  # each order is its own transaction, like real checkouts
        self.pending_bank_transfers(users)
        self.reviews(users)
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
        self.stdout.write(f"\n  Admin     admin@sku-fashion.local\n  Staff     staff@sku-fashion.local\n"
                          f"  Customer  dara@example.com (and 4 more customers)\n  Password  {password}\n")

    # ---- accounts ----------------------------------------------------------
    def accounts(self, password):
        def user(email, first, last, role, phone=""):
            u, _ = User.objects.get_or_create(email=email, defaults={"first_name": first, "last_name": last,
                                                                      "role": role, "phone": phone})
            u.first_name, u.last_name, u.role = first, last, role
            u.set_password(password)
            u.save()
            return u

        admin = user("admin@sku-fashion.local", "Kimsear", "Seav", User.Role.ADMIN)
        staff = user("staff@sku-fashion.local", "Phakdey", "Sin", User.Role.STAFF)
        user("staff2@sku-fashion.local", "Samnang", "Sophat", User.Role.STAFF)
        customers = []
        for email, first, last, province, district in [
            ("dara@example.com", "Dara", "Chan", "Phnom Penh", "Chamkar Mon"),
            ("sokha@example.com", "Sokha", "Kim", "Phnom Penh", "Toul Kork"),
            ("vibol@example.com", "Vibol", "Meas", "Siem Reap", "Siem Reap"),
            ("channary@example.com", "Channary", "Ouk", "Battambang", "Battambang"),
            ("rithy@example.com", "Rithy", "Long", "Kampot", "Kampong Bay"),
        ]:
            c = user(email, first, last, User.Role.CUSTOMER, "012 345 678")
            Address.objects.get_or_create(user=c, recipient=f"{first} {last}", defaults={
                "phone": "012 345 678", "province": province, "district": district,
                "line_1": f"No. {random.randint(10, 200)}, St. {random.randint(100, 600)}", "is_default": True})
            customers.append(c)
        return {"admin": admin, "staff": staff, "customers": customers}

    # ---- catalog -------------------------------------------------------------
    def catalog(self, staff):
        tree = {"Women": ["Women Tops", "Dresses", "Women Bottoms"], "Men": ["Men Shirts", "Men Pants", "Outerwear"],
                "Accessories": ["Bags"]}
        cats = {}
        for top, children in tree.items():
            cats[top] = Category.objects.create(name=top)
            for child in children:
                cats[child] = Category.objects.create(name=child, parent=cats[top])
        SizeChart.objects.create(category=cats["Women"], name="Women's sizes",
                                 content="Size | Bust (cm) | Waist (cm) | Hip (cm)\nXS | 80 | 62 | 86\nS | 84 | 66 | 90\n"
                                         "M | 88 | 70 | 94\nL | 94 | 76 | 100\nXL | 100 | 82 | 106")
        SizeChart.objects.create(category=cats["Men"], name="Men's sizes",
                                 content="Size | Chest (cm) | Length (cm)\nS | 92 | 70\nM | 98 | 72\nL | 104 | 74\n"
                                         "XL | 110 | 76")
        SizeChart.objects.create(category=cats["Men Pants"], name="Men's waist sizes",
                                 content="Size | Waist (cm) | Inseam (cm)\n30 | 76 | 81\n32 | 81 | 81\n34 | 86 | 82")
        brands = {n: Brand.objects.create(name=n) for n in ["Mekong Denim", "Angkor Atelier", "Tonle Basics",
                                                          "Kampot Linen"]}
        materials = {n: Material.objects.create(name=n) for n in ["Cotton", "Linen", "Denim", "Polyester", "Silk"]}
        colors = {n: Color.objects.create(name=n, hex_code=h, sort_order=i) for i, (n, h) in enumerate(COLORS)}
        sizes = {n: Size.objects.create(name=n, sort_order=i) for i, n in enumerate(SIZES)}

        inventory = InventoryService(staff)
        for i, (name, cat, brand, price, mats, cols, szs, desc) in enumerate(PRODUCTS):
            product = Product.objects.create(name=name, category=cats[cat], brand=brands[brand],
                                             base_price=Decimal(price), description=desc)
            product.materials.set([materials[m] for m in mats])
            for j, col in enumerate(cols):
                filename = f"{product.slug}-{col.lower().replace(' ', '-')}.png"
                ProductImage.objects.create(product=product, color=colors[col], is_primary=(j == 0),
                                            image=placeholder_image(name, colors[col].hex_code, filename))
            created, _ = VariantGenerator(product).generate([sizes[s] for s in szs], [colors[c] for c in cols],
                                                            safety_level=5)
            for v in created:
                if v.size.name in ("XL", "34"):
                    ProductVariant.objects.filter(pk=v.pk).update(price_delta=Decimal("3.00"))
                qty = random.choice([0, 3, 8, 12, 20, 25, 30]) if i % 4 == 0 else random.choice([12, 18, 25, 40])
                if qty:
                    inventory.adjust(v, qty, "Initial stock — received from supplier")

    # ---- shipping & promotions --------------------------------------------------
    def shipping(self):
        standard = ShippingMethod.objects.create(name="Standard delivery (2–3 days)", base_fee=Decimal("3.00"),
                                                 free_threshold=Decimal("60.00"))
        express = ShippingMethod.objects.create(name="Express delivery (same day)", base_fee=Decimal("6.00"))
        ShippingMethod.objects.create(name="Store pick-up (Phnom Penh)", base_fee=Decimal("0.00"))
        for method, fee in [(standard, "1.50"), (express, "3.50")]:
            ShippingRate.objects.create(method=method, province="Phnom Penh", fee=Decimal(fee))
            ShippingRate.objects.create(method=method, province="Kandal", fee=Decimal(fee) + 1)

    def promotions(self):
        now = timezone.now()
        sale = Campaign.objects.create(name="Rainy Season Sale", discount_type=DiscountType.PERCENT,
                                       discount_value=Decimal("20"), start_at=now - timedelta(days=10),
                                       end_at=now + timedelta(days=20))
        sale.categories.set(Category.objects.filter(name="Dresses"))
        sale.products.set(Product.objects.filter(name="Light Rain Jacket"))
        Coupon.objects.create(code="WELCOME10", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"),
                              min_spend=Decimal("20.00"), per_user_limit=1, start_at=now - timedelta(days=60),
                              end_at=now + timedelta(days=60))
        Coupon.objects.create(code="FIVEOFF", discount_type=DiscountType.FIXED, discount_value=Decimal("5.00"),
                              min_spend=Decimal("40.00"), usage_limit=100, start_at=now - timedelta(days=30),
                              end_at=now + timedelta(days=30))
        Coupon.objects.create(code="SUMMER25", discount_type=DiscountType.PERCENT, discount_value=Decimal("25"),
                              start_at=now - timedelta(days=120), end_at=now - timedelta(days=60))  # expired

    # ---- orders ---------------------------------------------------------------------
    def orders(self, users):
        staff, customers = users["staff"], users["customers"]
        variants = list(ProductVariant.objects.filter(stock_qty__gte=4).select_related("product"))
        methods = list(ShippingMethod.objects.all())
        factory = RequestFactory()
        now = timezone.now()
        plan = []  # (days_ago, final_status, provider)
        for days_ago in range(29, -1, -1):
            for _ in range(random.choice([0, 1, 1, 2, 2, 3])):
                if days_ago > 6:
                    final = random.choice([OrderStatus.COMPLETED] * 6 + [OrderStatus.CANCELLED])
                elif days_ago > 1:
                    final = random.choice([OrderStatus.COMPLETED, OrderStatus.SHIPPED, OrderStatus.SHIPPED,
                                           OrderStatus.PREPARING])
                else:
                    final = random.choice([OrderStatus.PREPARING, OrderStatus.PAID, OrderStatus.PENDING_PAYMENT])
                provider = "BANK_TRANSFER" if final in (OrderStatus.PAID, OrderStatus.PENDING_PAYMENT) \
                    else random.choice(["COD", "BANK_TRANSFER"])
                plan.append((days_ago, final, provider))

        for n, (days_ago, final, provider) in enumerate(plan):
            customer = random.choice(customers)
            request = factory.get("/")
            request.user, request.session = customer, SessionStore()
            cart = CartService(request)
            for v in random.sample(variants, random.choice([1, 1, 2, 3])):
                v.refresh_from_db()
                if v.stock_qty >= 2:
                    cart.add(v, random.choice([1, 1, 2]))
            if cart.summary().is_empty:
                continue
            address = customer.addresses.first()
            order = CheckoutService(customer, cart).place_order(
                address={"recipient": address.recipient, "phone": address.phone, "province": address.province,
                         "district": address.district, "line_1": address.line_1},
                shipping_method=random.choice(methods), provider_code=provider,
                coupon_code="FIVEOFF" if n % 5 == 0 and cart.summary().total >= 40 else "")
            self.advance(order, final, provider, staff)
            placed = now - timedelta(days=days_ago, hours=random.randint(0, 10), minutes=random.randint(0, 59))
            self.backdate(order, placed)

    def pending_bank_transfers(self, users):
        """Two fresh bank-transfer orders for demonstrating UC-08 / UC-16:
        one with a receipt waiting for reconciliation, one still unpaid."""
        factory = RequestFactory()
        variant = ProductVariant.objects.filter(stock_qty__gte=5).select_related("product").first()
        method = ShippingMethod.objects.first()
        for customer, with_receipt in [(users["customers"][0], True), (users["customers"][1], False)]:
            request = factory.get("/")
            request.user, request.session = customer, SessionStore()
            cart = CartService(request)
            cart.add(variant, 1)
            a = customer.addresses.first()
            order = CheckoutService(customer, cart).place_order(
                address={"recipient": a.recipient, "phone": a.phone, "province": a.province,
                         "district": a.district, "line_1": a.line_1},
                shipping_method=method, provider_code="BANK_TRANSFER")
            if with_receipt:
                receipt = placeholder_image(f"ABA transfer {order.order_no}", "#E8EEF5", f"{order.order_no}.png")
                PaymentService(customer).upload_receipt(order.payments.first(), receipt)
            self.backdate(order, timezone.now() - timedelta(hours=3 if with_receipt else 1))

    # ---- reviews -----------------------------------------------------------
    REVIEW_TEXT = {
        5: ["Fits perfectly and the fabric feels great. Ordering another colour.",
            "Exactly like the photos. Fast delivery to Phnom Penh too.",
            "Very comfortable in this heat, breathes well.", ""],
        4: ["Good quality for the price. Slightly long in the sleeves.",
            "Nice colour, runs a little small — size up.", "Happy with it overall."],
        3: ["Okay. The material is thinner than I expected.", "Average, does the job."],
        2: ["Colour faded after two washes."],
        1: ["Seams came apart after a week."],
    }

    def reviews(self, users):
        """Reviews on about half of the completed items: most published, a few
        waiting in the moderation queue, one rejected. Dara keeps at least one
        completed item unreviewed so the demo can write a review live."""
        staff = users["staff"]
        dara = users["customers"][0]
        items = list(OrderItem.objects.filter(order__status=OrderStatus.COMPLETED)
                     .select_related("order__user").order_by("order__placed_at", "id"))
        kept_for_demo = next((i for i in reversed(items) if i.order.user == dara), None)
        now = timezone.now()
        reviewed = [i for i in items if i != kept_for_demo and random.random() < 0.55]
        for n, item in enumerate(reviewed):
            rating = random.choice([5, 5, 5, 4, 4, 4, 3, 2, 1])
            text = random.choice(self.REVIEW_TEXT[rating])
            spam = n == 2  # one advert, so the rejected tab is not empty
            if spam:
                rating, text = 5, "Cheaper copies of this on my page — message 012 888 999!"
            review = ReviewService(item.order.user).submit(item, rating, text)
            completed = item.order.history.filter(to_status=OrderStatus.COMPLETED).latest("created_at").created_at
            submitted = min(completed + timedelta(days=random.randint(1, 3), hours=random.randint(0, 8)),
                            now - timedelta(hours=random.randint(2, 20)))
            moderated = None
            if n < len(reviewed) - 3:  # the newest three stay pending
                if spam:
                    ReviewModerationService(staff).reject(review, "Advertising and phone numbers are not allowed "
                                                                  "in reviews.")
                else:
                    ReviewModerationService(staff).approve(review)
                moderated = min(submitted + timedelta(hours=random.randint(2, 18)), now)
            Review.objects.filter(pk=review.pk).update(submitted_at=submitted, moderated_at=moderated)

    @staticmethod
    def backdate(order, placed):
        """Place the order at `placed` and spread its later steps out in time
        (a few hours to a day apart, never in the future), so the status
        history looks like a real order instead of one instant."""
        from inventory.models import StockMovement
        from payments.models import Payment
        from shipping.models import Shipment

        now = timezone.now()
        history = list(order.history.order_by("created_at", "pk"))
        steps = max(len(history) - 1, 1)
        gap = min(timedelta(hours=random.choice([5, 9, 16])), (now - placed) / (steps + 1))
        when = {}
        for i, entry in enumerate(history):
            entry.created_at = placed + gap * i
            when[entry.to_status] = entry.created_at
        order.history.model.objects.bulk_update(history, ["created_at"])

        Order.objects.filter(pk=order.pk).update(placed_at=placed)
        StockMovement.objects.filter(reference=order.order_no, type="OUT").update(created_at=placed)
        if OrderStatus.CANCELLED in when:
            StockMovement.objects.filter(reference=order.order_no, type="IN").update(
                created_at=when[OrderStatus.CANCELLED])
        Payment.objects.filter(order=order).update(created_at=placed)
        paid = when.get(OrderStatus.PAID) or when.get(OrderStatus.COMPLETED)
        if paid:
            Payment.objects.filter(order=order, paid_at__isnull=False).update(paid_at=paid, verified_at=paid)
        if OrderStatus.SHIPPED in when:
            Shipment.objects.filter(order=order).update(shipped_at=when[OrderStatus.SHIPPED])
        if OrderStatus.COMPLETED in when:
            Shipment.objects.filter(order=order).update(delivered_at=when[OrderStatus.COMPLETED])

    def advance(self, order, final, provider, staff):
        """Walk the order through the real workflow up to `final`."""
        if final == OrderStatus.CANCELLED:
            OrderWorkflow(order, order.user).cancel("Changed my mind")
            return
        if final == OrderStatus.PENDING_PAYMENT:
            return
        if provider == "BANK_TRANSFER":
            payment = order.payments.first()
            receipt = placeholder_image(f"ABA transfer {order.order_no}", "#E8EEF5", f"{order.order_no}.png")
            PaymentService(order.user).upload_receipt(payment, receipt)
            PaymentService(staff).reconcile(payment, f"ABA-{random.randint(100000, 999999)}")
            if final == OrderStatus.PAID:
                return
            OrderWorkflow(order, staff).transition(OrderStatus.PREPARING)
        if final == OrderStatus.PREPARING:
            return
        ShipmentService(staff).create(order, random.choice(["J&T Express", "VET Express", "Grab Express"]),
                                      f"TRK{random.randint(10000000, 99999999)}")
        if final == OrderStatus.COMPLETED:
            OrderWorkflow(order, staff).transition(OrderStatus.COMPLETED)
