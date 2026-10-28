import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone

from core.provinces import PROVINCE_CHOICES


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "PENDING_PAYMENT", "Pending Payment"
    PAID = "PAID", "Paid"
    PREPARING = "PREPARING", "Preparing"
    SHIPPED = "SHIPPED", "Shipped"
    COMPLETED = "COMPLETED", "Completed"
    CANCELLED = "CANCELLED", "Cancelled"


# Permitted status transitions — the table in SA document §4.2.4 (UC-15).
TRANSITIONS = {
    OrderStatus.PENDING_PAYMENT: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.PREPARING, OrderStatus.CANCELLED},
    OrderStatus.PREPARING: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.COMPLETED},
    OrderStatus.COMPLETED: set(),
    OrderStatus.CANCELLED: set(),
}

CANCELLABLE = {OrderStatus.PENDING_PAYMENT, OrderStatus.PAID, OrderStatus.PREPARING}


class Order(models.Model):
    order_no = models.CharField(max_length=20, unique=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=20, choices=OrderStatus.choices, db_index=True)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2,
                                   help_text="Sum of list prices before any discount.")
    discount_total = models.DecimalField(max_digits=12, decimal_places=2,
                                         help_text="Campaign discounts plus coupon discount.")
    tax_total = models.DecimalField(max_digits=12, decimal_places=2)
    shipping_fee = models.DecimalField(max_digits=12, decimal_places=2)
    grand_total = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")

    ship_recipient = models.CharField(max_length=150)
    ship_phone = models.CharField(max_length=30)
    ship_province = models.CharField(max_length=50, choices=PROVINCE_CHOICES)
    ship_district = models.CharField(max_length=100)
    ship_line_1 = models.CharField(max_length=255)
    shipping_method = models.ForeignKey("shipping.ShippingMethod", on_delete=models.PROTECT, related_name="orders")

    placed_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-placed_at"]

    def __str__(self):
        return self.order_no

    @staticmethod
    def generate_order_no():
        """e.g. SF261028-4F9A2C — date for humans, random suffix for uniqueness."""
        while True:
            candidate = f"SF{timezone.localdate():%y%m%d}-{secrets.token_hex(3).upper()}"
            if not Order.objects.filter(order_no=candidate).exists():
                return candidate

    # ---- workflow ----------------------------------------------------------
    def allowed_transitions(self):
        return [s for s in OrderStatus if s in TRANSITIONS[OrderStatus(self.status)]]

    def can_transition_to(self, status):
        return status in TRANSITIONS[OrderStatus(self.status)]

    @property
    def is_cancellable(self):
        return self.status in CANCELLABLE

    @property
    def payment(self):
        """The most recent payment record (uses prefetched payments if present)."""
        payments = list(self.payments.all())
        return payments[-1] if payments else None

    @property
    def merchandise_total(self):
        return self.subtotal - self.discount_total


class OrderItem(models.Model):
    """A snapshot of what was bought, at the price charged (FR-X04)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    # PROTECT: a variant that appears in any order can never be deleted (SA §5).
    variant = models.ForeignKey("catalog.ProductVariant", on_delete=models.PROTECT, related_name="order_items")
    campaign = models.ForeignKey("promotions.Campaign", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="order_items")
    product_name = models.CharField(max_length=200)
    variant_spec = models.CharField(max_length=150)
    original_price = models.DecimalField(max_digits=10, decimal_places=2)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField()
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.quantity} × {self.product_name} ({self.variant_spec})"


class OrderStatusHistory(models.Model):
    """Every status change with operator and time (FR-X07, UC-15 step 5)."""

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="history")
    from_status = models.CharField(max_length=20, choices=OrderStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=OrderStatus.choices)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                             related_name="order_status_changes", help_text="Empty when the system acted.")
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        verbose_name_plural = "order status history"

    def __str__(self):
        return f"{self.order}: {self.from_status or '—'} → {self.to_status}"
