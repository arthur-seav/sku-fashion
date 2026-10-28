from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Address
from catalog.models import ProductVariant
from cart.models import CartItem
from core.testing import make_product, make_staff, make_user, make_variant
from inventory.models import StockMovement
from payments.models import Payment
from promotions.models import Campaign, Coupon, CouponRedemption, DiscountType
from shipping.models import ShippingMethod, ShippingRate

from .models import Order, OrderStatus

NOW = timezone.now()


class CheckoutTestCase(TestCase):
    def setUp(self):
        self.customer = make_user("buyer@example.com")
        Address.objects.create(user=self.customer, recipient="Dara", phone="012345678", province="Phnom Penh",
                               district="Chamkar Mon", line_1="St. 310 #12", is_default=True)
        self.product = make_product("Linen Shirt", "30.00")
        self.v1 = make_variant(self.product, color="White", size="M", stock=5)            # 30.00
        self.v2 = make_variant(self.product, color="Black", size="L", stock=2, delta="5.00")  # 35.00
        self.express = ShippingMethod.objects.create(name="Express", base_fee=Decimal("4.00"),
                                                     free_threshold=Decimal("200.00"))
        ShippingRate.objects.create(method=self.express, province="Phnom Penh", fee=Decimal("1.50"))
        self.pickup = ShippingMethod.objects.create(name="Store pick-up", base_fee=Decimal("0.00"))
        self.client.force_login(self.customer)
        self.url = reverse("orders:checkout")

    def add(self, variant, qty):
        self.client.post(reverse("cart:add"), {"variant": variant.pk, "quantity": qty})

    def form(self, **overrides):
        data = {"recipient": "Dara", "phone": "012345678", "province": "Phnom Penh", "district": "Chamkar Mon",
                "line_1": "St. 310 #12", "shipping_method": self.express.pk, "payment_method": "COD",
                "coupon_code": "", "action": "place"}
        data.update(overrides)
        return data

    def place(self, **overrides):
        self.client.get(self.url)  # shows the checkout page → remembers prices shown
        return self.client.post(self.url, self.form(**overrides))


class PlaceOrderTests(CheckoutTestCase):
    """UC-07 main flow, FR-X04 / X05 / X06 / X08."""

    def test_cash_on_delivery_order(self):
        self.add(self.v1, 2)
        self.add(self.v2, 1)
        response = self.place()
        order = Order.objects.get()
        self.assertRedirects(response, f"{reverse('orders:order_detail', args=[order.order_no])}?placed=1")

        # Totals: 2×30 + 35 = 95; VAT 10% on 95 = 9.50; Phnom Penh express rate 1.50.
        self.assertEqual(order.subtotal, Decimal("95.00"))
        self.assertEqual(order.discount_total, Decimal("0.00"))
        self.assertEqual(order.tax_total, Decimal("9.50"))
        self.assertEqual(order.shipping_fee, Decimal("1.50"))
        self.assertEqual(order.grand_total, Decimal("106.00"))
        self.assertRegex(order.order_no, r"^SF\d{6}-[0-9A-F]{6}$")

        # COD starts in Preparing (FR-X08); payment is Pending.
        self.assertEqual(order.status, OrderStatus.PREPARING)
        payment = Payment.objects.get()
        self.assertEqual((payment.provider, payment.status, payment.amount), ("COD", "PENDING", order.grand_total))

        # Snapshot of name, variant and price (FR-X04).
        item = order.items.get(variant=self.v2)
        self.assertEqual((item.product_name, item.unit_price, item.line_total),
                         ("Linen Shirt", Decimal("35.00"), Decimal("35.00")))
        self.assertIn("Black / L", item.variant_spec)

        # Stock deducted with movements referencing the order (FR-X06, FR-X07).
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.stock_qty, 3)
        self.assertEqual(StockMovement.objects.filter(reference=order.order_no, type="OUT").count(), 2)

        # Cart emptied; history has the initial entry.
        self.assertFalse(CartItem.objects.exists())
        self.assertEqual(order.history.get().to_status, OrderStatus.PREPARING)

    def test_bank_transfer_starts_pending_payment(self):
        self.add(self.v1, 1)
        self.place(payment_method="BANK_TRANSFER")
        order = Order.objects.get()
        self.assertEqual(order.status, OrderStatus.PENDING_PAYMENT)
        page = self.client.get(reverse("orders:order_detail", args=[order.order_no]) + "?placed=1")
        self.assertContains(page, order.order_no)
        self.assertContains(page, "000 123 456")  # bank details shown (UC-07 7a)

    def test_store_pickup_and_free_threshold(self):
        self.add(self.v1, 1)
        self.place(shipping_method=self.pickup.pk)
        self.assertEqual(Order.objects.get().shipping_fee, Decimal("0.00"))

    def test_free_shipping_threshold(self):
        ShippingMethod.objects.filter(pk=self.express.pk).update(free_threshold=Decimal("50.00"))
        self.add(self.v1, 2)  # 60.00
        self.place()
        self.assertEqual(Order.objects.get().shipping_fee, Decimal("0.00"))


class CheckoutDiscountTests(CheckoutTestCase):
    def test_campaign_and_coupon_and_vat_on_discounted_subtotal(self):
        campaign = Campaign.objects.create(name="Linen Week", discount_type=DiscountType.PERCENT,
                                           discount_value=Decimal("10"), start_at=NOW - timedelta(days=1),
                                           end_at=NOW + timedelta(days=1))
        campaign.products.add(self.product)
        coupon = Coupon.objects.create(code="FIVE", discount_type=DiscountType.FIXED, discount_value=Decimal("5"),
                                       start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1))
        self.add(self.v1, 2)  # 60 list, 54 after campaign
        self.place(coupon_code="five")
        order = Order.objects.get()
        # subtotal 60, campaign 6, coupon 5 → taxable 49, VAT 4.90, shipping 1.50
        self.assertEqual(order.discount_total, Decimal("11.00"))
        self.assertEqual(order.tax_total, Decimal("4.90"))
        self.assertEqual(order.grand_total, Decimal("55.40"))
        self.assertEqual(order.items.get().campaign, campaign)
        redemption = CouponRedemption.objects.get()
        self.assertEqual((redemption.coupon, redemption.order, redemption.discount_amount),
                         (coupon, order, Decimal("5.00")))  # FR-X10

    def test_apply_coupon_shows_discount_without_placing(self):
        Coupon.objects.create(code="TEN", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"),
                              start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1))
        self.add(self.v1, 1)
        response = self.client.post(self.url, self.form(coupon_code="TEN", action="apply"))
        self.assertContains(response, "TEN applied")
        self.assertEqual(response.context["totals"].coupon_discount, Decimal("3.00"))
        self.assertFalse(Order.objects.exists())

    def test_invalid_coupon_reported_and_no_order(self):
        self.add(self.v1, 1)
        response = self.place(coupon_code="NOPE")
        self.assertContains(response, "does not exist")
        self.assertFalse(Order.objects.exists())

    def test_coupon_usage_limits(self):
        Coupon.objects.create(code="ONCE", discount_type=DiscountType.FIXED, discount_value=Decimal("1"),
                              per_user_limit=1, start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1))
        self.add(self.v1, 1)
        self.place(coupon_code="ONCE")
        self.add(self.v1, 1)
        response = self.place(coupon_code="ONCE")
        self.assertContains(response, "maximum allowed")
        self.assertEqual(Order.objects.count(), 1)

    def test_total_usage_limit(self):
        Coupon.objects.create(code="FIRST1", discount_type=DiscountType.FIXED, discount_value=Decimal("1"),
                              usage_limit=1, start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1))
        self.add(self.v1, 1)
        self.place(coupon_code="FIRST1")
        other = make_user("other@example.com")
        self.client.force_login(other)
        self.add(self.v1, 1)
        response = self.place(coupon_code="FIRST1")
        self.assertContains(response, "reached its usage limit")


class CheckoutExceptionTests(CheckoutTestCase):
    """UC-07 exception flows 1a and 9a."""

    def test_stock_dropped_returns_to_cart(self):
        self.add(self.v2, 2)
        self.client.get(self.url)
        ProductVariant.objects.filter(pk=self.v2.pk).update(stock_qty=1)
        response = self.client.post(self.url, self.form(), follow=True)
        self.assertRedirects(response, reverse("cart:detail"))
        self.assertContains(response, "Only 1 left")
        self.assertFalse(Order.objects.exists())

    def test_price_changed_since_checkout_page(self):
        self.add(self.v1, 1)
        self.client.get(self.url)
        type(self.product).objects.filter(pk=self.product.pk).update(base_price=Decimal("33.00"))
        response = self.client.post(self.url, self.form(), follow=True)
        self.assertContains(response, "changed from 30.00 to 33.00")
        self.assertFalse(Order.objects.exists())

    def test_failure_inside_transaction_rolls_everything_back(self):
        """FR-X05: order, items, stock, payment and coupon succeed or fail together."""
        Coupon.objects.create(code="TEN", discount_type=DiscountType.PERCENT, discount_value=Decimal("10"),
                              start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1))
        self.add(self.v1, 2)
        self.client.get(self.url)
        with mock.patch("payments.providers.CashOnDeliveryProvider.create_payment",
                        side_effect=RuntimeError("payment service down")):
            with self.assertRaises(RuntimeError):
                self.client.post(self.url, self.form(coupon_code="TEN"))
        self.assertFalse(Order.objects.exists())
        self.assertFalse(StockMovement.objects.exists())
        self.assertFalse(CouponRedemption.objects.exists())
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.stock_qty, 5)
        self.assertEqual(CartItem.objects.get().quantity, 2)  # cart kept

    def test_concurrent_sale_of_last_items_rolls_back(self):
        """Another order takes the stock between validation and deduction."""
        from inventory.services import InsufficientStock, InventoryService
        self.add(self.v1, 1)
        self.add(self.v2, 2)
        self.client.get(self.url)
        original = InventoryService.deduct

        def racing_deduct(service, variant, qty, reference, reason="Order placed"):
            if variant.pk == self.v2.pk:  # someone else bought them a moment ago
                raise InsufficientStock(variant, qty, 0)
            return original(service, variant, qty, reference, reason)

        with mock.patch.object(InventoryService, "deduct", racing_deduct):
            response = self.client.post(self.url, self.form(), follow=True)
        self.assertRedirects(response, reverse("cart:detail"))
        self.assertFalse(Order.objects.exists())
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.stock_qty, 5)  # v1's deduction was rolled back

    def test_empty_cart_redirects(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, reverse("cart:detail"))


class CheckoutAccessTests(TestCase):
    def test_guest_must_sign_in(self):
        response = self.client.get(reverse("orders:checkout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:login"), response.url)

    def test_staff_cannot_check_out(self):
        self.client.force_login(make_staff())
        self.assertEqual(self.client.get(reverse("orders:checkout")).status_code, 403)

    def test_customer_sees_only_own_orders(self):
        owner = make_user("owner@example.com")
        method = ShippingMethod.objects.create(name="Std", base_fee=Decimal("1"))
        order = Order.objects.create(order_no="SF000000-AAAAAA", user=owner, status=OrderStatus.PREPARING,
                                     subtotal=1, discount_total=0, tax_total=0, shipping_fee=0, grand_total=1,
                                     ship_recipient="x", ship_phone="x", ship_province="Kep", ship_district="x",
                                     ship_line_1="x", shipping_method=method)
        self.client.force_login(make_user("intruder@example.com"))
        self.assertEqual(self.client.get(reverse("orders:order_detail", args=[order.order_no])).status_code, 404)
