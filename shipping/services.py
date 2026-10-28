"""Delivery fee quotes (DFD 6.7 Quote Shipping Fee, UC-07 step 4)."""

from dataclasses import dataclass
from decimal import Decimal

from core.money import ZERO

from .models import ShippingMethod, ShippingRate


@dataclass
class ShippingQuote:
    method: ShippingMethod
    fee: Decimal
    reason: str  # "free threshold", "province rate", "base fee"


class ShippingQuoteService:
    @staticmethod
    def active_methods():
        return ShippingMethod.objects.filter(is_active=True)

    def quote(self, method, province, amount):
        """Find method → look up province rate → apply free threshold."""
        if method.free_threshold is not None and amount >= method.free_threshold:
            return ShippingQuote(method, ZERO, "free threshold")
        rate = ShippingRate.objects.filter(method=method, province=province).first()
        if rate is not None:
            return ShippingQuote(method, rate.fee, "province rate")
        return ShippingQuote(method, method.base_fee, "base fee")
