import re
from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction

from .models import ProductVariant


class SkuBuilder:
    """SKU code = product code + color code + size code, e.g. P0012-BLK-M (UC-13 step 5)."""

    @staticmethod
    def _code(text, length):
        cleaned = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        return cleaned[:length] or "X"

    def build(self, product, color, size):
        return f"P{product.pk:04d}-{self._code(color.name, 3)}-{self._code(size.name, 4)}"

    def unique(self, product, color, size, taken):
        """Append -2, -3 … in the rare case two colors share a 3-letter code."""
        base = self.build(product, color, size)
        sku, n = base, 2
        while sku in taken or ProductVariant.objects.filter(sku=sku).exists():
            sku = f"{base}-{n}"
            n += 1
        taken.add(sku)
        return sku


@dataclass
class VariantCombination:
    color: object
    size: object
    sku: str
    existing: object = None  # the variant already defined for this combination, if any

    @property
    def is_new(self):
        return self.existing is None


class VariantGenerator:
    """Bulk-generates variants from selected sizes × colors (UC-13, FR-S03).

    Existing combinations are skipped and kept; new variants start with a
    stock quantity of zero — stock is added through Adjust Stock so every
    change is recorded as a movement (FR-X07).
    """

    def __init__(self, product, sku_builder=None):
        self.product = product
        self.sku_builder = sku_builder or SkuBuilder()

    def preview(self, sizes, colors):
        existing = {(v.color_id, v.size_id): v
                    for v in self.product.variants.select_related("color", "size")}
        taken = set()
        combos = []
        for color in sorted(colors, key=lambda c: (c.sort_order, c.name)):
            for size in sorted(sizes, key=lambda s: (s.sort_order, s.name)):
                found = existing.get((color.pk, size.pk))
                sku = found.sku if found else self.sku_builder.unique(self.product, color, size, taken)
                combos.append(VariantCombination(color=color, size=size, sku=sku, existing=found))
        return combos

    @transaction.atomic
    def generate(self, sizes, colors, price_delta=Decimal("0.00"), safety_level=5):
        combos = self.preview(sizes, colors)
        created = [
            ProductVariant.objects.create(
                product=self.product, color=c.color, size=c.size, sku=c.sku,
                price_delta=price_delta, safety_level=safety_level,
            )
            for c in combos if c.is_new
        ]
        skipped = sum(1 for c in combos if not c.is_new)
        return created, skipped
