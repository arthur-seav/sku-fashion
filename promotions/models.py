from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from core.money import ZERO, to_money


class DiscountType(models.TextChoices):
    PERCENT = "PERCENT", "Percentage (%)"
    FIXED = "FIXED", "Fixed amount"


class DiscountRule(models.Model):
    """Shared shape of coupons and campaigns: a discount valid for a period."""

    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    discount_value = models.DecimalField(max_digits=10, decimal_places=2,
                                         validators=[MinValueValidator(Decimal("0.01"))])
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        abstract = True

    def clean(self):
        if self.start_at and self.end_at and self.end_at <= self.start_at:
            raise ValidationError({"end_at": "The end must be after the start."})
        if self.discount_type == DiscountType.PERCENT and self.discount_value and self.discount_value > 100:
            raise ValidationError({"discount_value": "A percentage cannot exceed 100."})

    def is_running(self, now=None):
        now = now or timezone.now()
        return self.is_active and self.start_at <= now <= self.end_at

    def discount_on(self, amount):
        """Discount for `amount`, never more than the amount itself."""
        amount = Decimal(amount)
        if amount <= 0:
            return ZERO
        if self.discount_type == DiscountType.PERCENT:
            return min(to_money(amount * self.discount_value / 100), amount)
        return min(to_money(self.discount_value), amount)

    @property
    def discount_label(self):
        if self.discount_type == DiscountType.PERCENT:
            return f"{self.discount_value.normalize():f}% off"
        return f"{self.discount_value} off"


class Campaign(DiscountRule):
    """A time-boxed discount on selected categories and/or products (FR-S09)."""

    name = models.CharField(max_length=150)
    categories = models.ManyToManyField("catalog.Category", through="CampaignCategory", blank=True,
                                        related_name="campaigns")
    products = models.ManyToManyField("catalog.Product", through="CampaignProduct", blank=True,
                                      related_name="campaigns")

    class Meta:
        ordering = ["-start_at"]

    def __str__(self):
        return self.name


class CampaignCategory(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    category = models.ForeignKey("catalog.Category", on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "category"], name="uniq_campaign_category")]


class CampaignProduct(models.Model):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE)
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["campaign", "product"], name="uniq_campaign_product")]


class Coupon(DiscountRule):
    """A code the customer enters at checkout (FR-S08)."""

    code = models.CharField(max_length=30, unique=True, help_text="Stored in upper case; customers can type any case.")
    min_spend = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO,
                                    validators=[MinValueValidator(ZERO)])
    usage_limit = models.PositiveIntegerField(null=True, blank=True, help_text="Total uses allowed. Empty = unlimited.")
    per_user_limit = models.PositiveIntegerField(null=True, blank=True,
                                                 help_text="Uses allowed per customer. Empty = unlimited.")

    class Meta:
        ordering = ["-start_at"]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)
