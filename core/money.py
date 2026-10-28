"""Money helpers shared by pricing, checkout and reports."""

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def to_money(value):
    """Round to cents, half-up (the way a receipt rounds)."""
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)
