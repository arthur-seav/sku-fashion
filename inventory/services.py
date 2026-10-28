"""The single entry point for every stock change (UC-14, FR-X06, FR-X07, FR-X12).

Manual adjustments, order deductions and cancellation restores all go
through `InventoryService`, so each change is applied atomically and leaves
exactly one `StockMovement` row behind.
"""

from django.db import transaction
from django.db.models import F

from catalog.models import ProductVariant

from .models import StockMovement


class InsufficientStock(Exception):
    def __init__(self, variant, requested, available):
        self.variant, self.requested, self.available = variant, requested, available
        super().__init__(f"{variant.product.name} ({variant.spec}): only {available} left, "
                         f"{requested} requested.")


class InventoryService:
    MANUAL_REFERENCE = "MANUAL"

    def __init__(self, user=None):
        self.user = user  # None means the system made the change

    # ---- public API ------------------------------------------------------
    def adjust(self, variant, change, reason):
        """Manual stock adjustment by Staff, with a stated reason (FR-S04)."""
        if change == 0:
            raise ValueError("The adjustment must change the stock level.")
        return self._apply(variant, change, reason, self.MANUAL_REFERENCE)

    def deduct(self, variant, quantity, reference, reason="Order placed"):
        """Remove stock for an order; fails instead of overselling (FR-X06)."""
        return self._apply(variant, -quantity, reason, reference)

    def restore(self, variant, quantity, reference, reason="Order cancelled"):
        """Return stock from a cancelled order (UC-10 step 3)."""
        return self._apply(variant, quantity, reason, reference)

    @staticmethod
    def low_stock_variants():
        """Active variants below their safety level, sold-out ones included (FR-X12)."""
        return (ProductVariant.objects.filter(is_active=True, product__is_active=True,
                                              stock_qty__lt=F("safety_level"))
                .select_related("product", "color", "size"))

    # ---- implementation ----------------------------------------------------
    @transaction.atomic
    def _apply(self, variant, change, reason, reference):
        rows = ProductVariant.objects.filter(pk=variant.pk)
        if change < 0:
            # The WHERE clause and the decrement run as one statement under a row
            # lock, so two concurrent checkouts can never both take the last item.
            rows = rows.filter(stock_qty__gte=-change)
        updated = rows.update(stock_qty=F("stock_qty") + change)
        current = ProductVariant.objects.select_related("product", "color", "size").get(pk=variant.pk)
        if not updated:
            raise InsufficientStock(current, -change, current.stock_qty)

        variant.stock_qty = current.stock_qty  # keep the caller's instance in step
        return StockMovement.objects.create(
            variant=current,
            type=StockMovement.Type.IN if change > 0 else StockMovement.Type.OUT,
            quantity=abs(change),
            reason=reason,
            reference=reference,
            user=self.user,
            balance_after=current.stock_qty,
        )
