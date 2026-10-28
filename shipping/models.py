from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models

from core.money import ZERO
from core.provinces import PROVINCE_CHOICES


class ShippingMethod(models.Model):
    """A delivery option. Store pick-up is simply a method with a zero fee."""

    name = models.CharField(max_length=100)
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO,
                                   validators=[MinValueValidator(ZERO)],
                                   help_text="Charged when the province has no specific rate.")
    free_threshold = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                         validators=[MinValueValidator(ZERO)],
                                         help_text="Orders at or above this amount ship free. Empty = never free.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["base_fee", "name"]

    def __str__(self):
        return self.name


class ShippingRate(models.Model):
    """A province-specific fee for a method (overrides the base fee)."""

    method = models.ForeignKey(ShippingMethod, on_delete=models.CASCADE, related_name="rates")
    province = models.CharField(max_length=50, choices=PROVINCE_CHOICES)
    fee = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.00"))])

    class Meta:
        ordering = ["method__name", "province"]
        constraints = [models.UniqueConstraint(fields=["method", "province"], name="uniq_method_province")]

    def __str__(self):
        return f"{self.method} → {self.province}"
