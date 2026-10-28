"""Coupon validation, redemption and release (FR-C04, FR-X10, UC-10).

Each failure has its own message so the customer knows exactly why a code
was refused.
"""

from django.db import transaction
from django.utils import timezone
from django.utils.formats import date_format

from core.templatetags.ui import money

from .models import Coupon, CouponRedemption


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

    @staticmethod
    def _check_usage(coupon, user):
        if coupon.usage_limit is not None and coupon.used_count >= coupon.usage_limit:
            raise CouponError(f"Coupon “{coupon.code}” has reached its usage limit.")
        if coupon.per_user_limit is not None and user is not None and user.is_authenticated:
            used_by_user = coupon.active_redemptions().filter(order__user=user).count()
            if used_by_user >= coupon.per_user_limit:
                raise CouponError(f"You have already used coupon “{coupon.code}” "
                                  f"{used_by_user} time(s), the maximum allowed.")

    @transaction.atomic
    def redeem(self, coupon, order, amount):
        """Called inside the checkout transaction. The coupon row is locked so
        two simultaneous checkouts cannot both take the last allowed use."""
        coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)
        self._check_usage(coupon, order.user)
        return CouponRedemption.objects.create(coupon=coupon, order=order, discount_amount=amount)

    def release(self, order):
        """UC-10: a cancelled order gives its coupon use back."""
        return CouponRedemption.objects.filter(order=order, released_at__isnull=True).update(released_at=self.now)

    @staticmethod
    def discount(coupon, amount):
        return coupon.discount_on(amount)
