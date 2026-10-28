from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class ReviewStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    APPROVED = "APPROVED", "Approved"
    REJECTED = "REJECTED", "Rejected"


class ReviewQuerySet(models.QuerySet):
    def published(self):
        """Only approved reviews are shown on the storefront (FR-S12)."""
        return self.filter(status=ReviewStatus.APPROVED)

    def for_product(self, product):
        return self.filter(order_item__variant__product=product)


class Review(models.Model):
    """A customer's rating of one purchased order item (FR-C08, UC-22).

    One review per order item (the SA ERD's unique `order_item_id`). It is
    published only after a staff member approves it (FR-S12, UC-23).
    """

    order_item = models.OneToOneField("orders.OrderItem", on_delete=models.CASCADE, related_name="review")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(max_length=1000, blank=True)
    status = models.CharField(max_length=10, choices=ReviewStatus.choices, default=ReviewStatus.PENDING,
                              db_index=True)
    submitted_at = models.DateTimeField(default=timezone.now,
                                        help_text="First submission, or the latest resubmission after an edit.")
    moderated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                     related_name="moderated_reviews")
    moderated_at = models.DateTimeField(null=True, blank=True)
    moderation_note = models.CharField(max_length=255, blank=True,
                                       help_text="Reason for a rejection; shown to the customer.")

    objects = ReviewQuerySet.as_manager()

    class Meta:
        ordering = ["-submitted_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(rating__gte=1, rating__lte=5), name="review_rating_1_to_5"),
        ]

    def __str__(self):
        return f"{self.rating}★ {self.order_item.product_name} ({self.get_status_display()})"

    @property
    def product(self):
        return self.order_item.variant.product

    @property
    def author_name(self):
        """Public byline: first name and last initial, e.g. "Dara C."."""
        user = self.order_item.order.user
        initial = f" {user.last_name[:1]}." if user.last_name else ""
        return f"{user.first_name}{initial}" or "Customer"

    @property
    def is_editable(self):
        """A customer can change a review until it is published."""
        return self.status != ReviewStatus.APPROVED
