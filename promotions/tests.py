from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalog.models import Category
from core.testing import make_product, make_staff, make_user, make_variant

from .models import Campaign, Coupon, DiscountType
from .pricing import PricingService
from .services import CouponError, CouponService

NOW = timezone.now()


def make_campaign(name="Sale", kind=DiscountType.PERCENT, value="20", products=(), categories=(), **extra):
    campaign = Campaign.objects.create(name=name, discount_type=kind, discount_value=Decimal(value),
                                       start_at=NOW - timedelta(days=1), end_at=NOW + timedelta(days=1), **extra)
    campaign.products.set(products)
    campaign.categories.set(categories)
    return campaign


def make_coupon(code="SAVE10", kind=DiscountType.PERCENT, value="10", **extra):
    defaults = {"start_at": NOW - timedelta(days=1), "end_at": NOW + timedelta(days=1)}
    defaults.update(extra)
    return Coupon.objects.create(code=code, discount_type=kind, discount_value=Decimal(value), **defaults)


class DiscountRuleTests(TestCase):
    def test_percent_and_fixed_discounts(self):
        pct = make_coupon(value="15")
        fixed = make_coupon(code="FIVE", kind=DiscountType.FIXED, value="5")
        self.assertEqual(pct.discount_on(Decimal("19.99")), Decimal("3.00"))  # 2.9985 → 3.00
        self.assertEqual(fixed.discount_on(Decimal("3.00")), Decimal("3.00"))  # never above the amount

    def test_percent_over_100_rejected(self):
        coupon = Coupon(code="X", discount_type=DiscountType.PERCENT, discount_value=Decimal("120"),
                        start_at=NOW, end_at=NOW + timedelta(days=1))
        with self.assertRaises(ValidationError):
            coupon.full_clean()

    def test_end_before_start_rejected(self):
        coupon = Coupon(code="X", discount_type=DiscountType.FIXED, discount_value=Decimal("1"),
                        start_at=NOW, end_at=NOW - timedelta(days=1))
        with self.assertRaises(ValidationError):
            coupon.full_clean()

    def test_code_stored_upper_case(self):
        self.assertEqual(make_coupon(code=" welcome ").code, "WELCOME")


class CouponValidationTests(TestCase):
    """FR-C04: unknown, inactive, not started, expired and below-minimum codes
    each produce their own message."""

    def setUp(self):
        self.user = make_user()
        self.service = CouponService()

    def assertRefused(self, code, amount, fragment):
        with self.assertRaisesMessage(CouponError, fragment):
            self.service.validate(code, self.user, Decimal(amount))

    def test_valid_code_any_case(self):
        coupon = make_coupon()
        self.assertEqual(self.service.validate("save10", self.user, Decimal("50")), coupon)

    def test_specific_errors(self):
        make_coupon(code="OFF", is_active=False)
        make_coupon(code="SOON", start_at=NOW + timedelta(days=2), end_at=NOW + timedelta(days=3))
        make_coupon(code="OLD", start_at=NOW - timedelta(days=3), end_at=NOW - timedelta(days=2))
        make_coupon(code="BIG", min_spend=Decimal("100"))
        self.assertRefused("", "10", "Enter a coupon code")
        self.assertRefused("NOPE", "10", "does not exist")
        self.assertRefused("OFF", "10", "no longer active")
        self.assertRefused("SOON", "10", "valid from")
        self.assertRefused("OLD", "10", "expired on")
        self.assertRefused("BIG", "99.99", "minimum spend of $100.00")


class PricingTests(TestCase):
    """FR-S09: campaigns on categories (incl. sub-categories) or products."""

    def setUp(self):
        self.women = Category.objects.create(name="Women")
        self.tops = Category.objects.create(name="Tops", parent=self.women)
        self.product = make_product(price="40.00", category=self.tops)
        self.variant = make_variant(self.product, stock=5)

    def test_no_campaign_means_list_price(self):
        quote = PricingService().quote(self.variant)
        self.assertEqual((quote.unit, quote.campaign), (Decimal("40.00"), None))

    def test_campaign_on_ancestor_category_applies(self):
        campaign = make_campaign(categories=[self.women])
        quote = PricingService().quote(self.variant)
        self.assertEqual((quote.unit, quote.campaign), (Decimal("32.00"), campaign))

    def test_best_of_overlapping_campaigns_wins(self):
        make_campaign(name="Small", value="10", products=[self.product])
        big = make_campaign(name="Big", kind=DiscountType.FIXED, value="15", categories=[self.tops])
        self.assertEqual(PricingService().quote(self.variant).campaign, big)

    def test_inactive_or_ended_campaign_ignored(self):
        make_campaign(products=[self.product], is_active=False)
        ended = make_campaign(products=[self.product])
        Campaign.objects.filter(pk=ended.pk).update(end_at=NOW - timedelta(minutes=1))
        self.assertIsNone(PricingService().quote(self.variant).campaign)

    def test_storefront_shows_sale_price_and_cart_discount(self):
        make_campaign(name="Mid-Season", products=[self.product])
        listing = self.client.get(reverse("catalog:product_list"))
        self.assertContains(listing, "$32.00")
        self.client.post(reverse("cart:add"), {"variant": self.variant.pk, "quantity": 2})
        summary = self.client.get(reverse("cart:detail")).context["summary"]
        self.assertEqual((summary.subtotal, summary.discount, summary.total),
                         (Decimal("80.00"), Decimal("16.00"), Decimal("64.00")))


class PromotionBackofficeTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())

    def test_lists_render(self):
        make_coupon()
        make_campaign(products=[make_product()])
        self.assertContains(self.client.get(reverse("promotions_bo:coupon_list")), "SAVE10")
        self.assertContains(self.client.get(reverse("promotions_bo:campaign_list")), "Running")

    def test_campaign_requires_a_target(self):
        response = self.client.post(reverse("promotions_bo:campaign_create"), {
            "name": "Empty", "discount_type": "PERCENT", "discount_value": "10",
            "start_at": "2026-11-01T00:00", "end_at": "2026-11-30T23:59", "is_active": "on"})
        self.assertContains(response, "Select at least one category or product")
