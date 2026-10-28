from django.conf import settings
from django.db import models

from core.validators import validate_image_size


class Payment(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    order = models.ForeignKey("orders.Order", on_delete=models.CASCADE, related_name="payments")
    provider = models.CharField(max_length=20, help_text="Code of the payment provider, e.g. COD.")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    transaction_ref = models.CharField(max_length=100, null=True, blank=True)
    receipt_image = models.ImageField(upload_to="receipts/%Y/%m/", null=True, blank=True,
                                      validators=[validate_image_size])
    verified_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="verified_payments")
    verified_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.order} · {self.provider} · {self.get_status_display()}"

    @property
    def provider_obj(self):
        from .providers import registry
        return registry.get(self.provider)

    @property
    def provider_label(self):
        return self.provider_obj.label

    @property
    def refunded_total(self):
        return sum((r.amount for r in self.refunds.all()), 0)

    @property
    def refundable_amount(self):
        return self.amount - self.refunded_total if self.status == self.Status.PAID else 0


class Refund(models.Model):
    """Money returned against a paid payment (FR-S06)."""

    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="refunds_issued")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Refund {self.amount} on {self.payment.order}"
