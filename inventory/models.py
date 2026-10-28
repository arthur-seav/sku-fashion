from django.conf import settings
from django.db import models


class StockMovement(models.Model):
    """One change to a variant's stock level (FR-S04, FR-X07)."""

    class Type(models.TextChoices):
        IN = "IN", "In"
        OUT = "OUT", "Out"

    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="movements")
    type = models.CharField(max_length=3, choices=Type.choices)
    quantity = models.PositiveIntegerField()
    reason = models.CharField(max_length=255)
    reference = models.CharField(max_length=50, blank=True, help_text="Order number, or MANUAL.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="stock_movements", help_text="Empty when the system made the change.")
    balance_after = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["reference"])]

    def __str__(self):
        sign = "+" if self.type == self.Type.IN else "−"
        return f"{self.variant.sku} {sign}{self.quantity} ({self.reason})"

    @property
    def signed_quantity(self):
        return self.quantity if self.type == self.Type.IN else -self.quantity
