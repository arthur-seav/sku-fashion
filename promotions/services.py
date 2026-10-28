"""Coupon validation (FR-C04).

Each failure has its own message so the customer knows exactly why a code
was refused. Usage-limit checks and redemption records are added together
with orders (step 9), because a redemption belongs to an order.
"""

from django.utils import timezone
from django.utils.formats import date_format

from core.templatetags.ui import money

from .models import Coupon


class CouponError(Exception):
    pass


class CouponService:
    def __init__(self, now=None):
        self.now = now or timezone.now()

    def validate(self, code, user, amount):
        code = (code or "").strip()
        if not code:
            raise CouponError("Enter a coupon code.")
        coupon = Coupon.objects.filter(code__iexact=code).first()
        if coupon is None:
            raise CouponError(f"Coupon “{code}” does not exist.")
        if not coupon.is_active:
            raise CouponError(f"Coupon “{coupon.code}” is no longer active.")
        if self.now < coupon.start_at:
            raise CouponError(f"Coupon “{coupon.code}” is valid from "
                              f"{date_format(timezone.localtime(coupon.start_at), 'j M Y')}.")
        if self.now > coupon.end_at:
            raise CouponError(f"Coupon “{coupon.code}” expired on "
                              f"{date_format(timezone.localtime(coupon.end_at), 'j M Y')}.")
        if amount < coupon.min_spend:
            raise CouponError(f"Coupon “{coupon.code}” needs a minimum spend of {money(coupon.min_spend)} "
                              f"(your items total {money(amount)}).")
        self._check_usage(coupon, user)
        return coupon

    def _check_usage(self, coupon, user):
        """Usage limits — implemented with coupon redemptions (step 9)."""

    @staticmethod
    def discount(coupon, amount):
        return coupon.discount_on(amount)
