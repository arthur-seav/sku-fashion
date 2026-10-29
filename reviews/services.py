"""Review rules: who may write a review (UC-22) and how staff moderate it (UC-23)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Avg, Count
from django.utils import timezone

from orders.models import OrderItem, OrderStatus

from .models import Review, ReviewStatus

RATING_LABELS = {1: "Poor", 2: "Fair", 3: "Good", 4: "Very good", 5: "Excellent"}


class ReviewError(Exception):
    """A review rule was broken; the message is shown to the user."""


class ReviewService:
    """Customer side: write or edit a review of a purchased item (FR-C08)."""

    def __init__(self, user):
        self.user = user

    def existing(self, item):
        try:
            return item.review
        except Review.DoesNotExist:
            return None

    def check_eligible(self, item):
        """Raise ReviewError unless the user may (re)write a review of `item`;
        return the existing review, if any."""
        if item.order.user_id != self.user.pk:
            raise ReviewError("You can only review items from your own orders.")
        if item.order.status != OrderStatus.COMPLETED:
            raise ReviewError(f"You can review this item once order {item.order.order_no} is completed.")
        review = self.existing(item)
        if review and not review.is_editable:
            raise ReviewError("Your review of this item is already published and can no longer be changed.")
        return review

    @transaction.atomic
    def submit(self, item, rating, comment=""):
        """Create the review, or resubmit an edited one. Either way it goes
        (back) to the moderation queue."""
        item = OrderItem.objects.select_for_update().select_related("order").get(pk=item.pk)
        review = self.check_eligible(item) or Review(order_item=item)
        if rating not in RATING_LABELS:
            raise ReviewError("Choose a rating from 1 to 5 stars.")
        review.rating = rating
        review.comment = (comment or "").strip()
        review.status = ReviewStatus.PENDING
        review.submitted_at = timezone.now()
        review.moderated_by, review.moderated_at, review.moderation_note = None, None, ""
        review.save()
        return review

    def items_to_review(self):
        """Purchased items in completed orders that have no review yet."""
        return (OrderItem.objects.filter(order__user=self.user, order__status=OrderStatus.COMPLETED,
                                         review__isnull=True)
                .select_related("order", "variant__product").order_by("-order__placed_at", "id"))

    def my_reviews(self):
        return (Review.objects.filter(order_item__order__user=self.user)
                .select_related("order_item__order", "order_item__variant__product", "moderated_by"))


class ReviewModerationService:
    """Back-office side: approve or reject reviews before publication (FR-S12)."""

    def __init__(self, user):
        self.user = user

    @transaction.atomic
    def approve(self, review):
        review = Review.objects.select_for_update().get(pk=review.pk)
        if review.status == ReviewStatus.APPROVED:
            raise ReviewError("This review is already published.")
        return self._decide(review, ReviewStatus.APPROVED, "")

    @transaction.atomic
    def reject(self, review, note):
        note = (note or "").strip()
        if not note:
            raise ReviewError("Give a reason for the rejection; the customer will see it.")
        review = Review.objects.select_for_update().get(pk=review.pk)
        if review.status == ReviewStatus.REJECTED:
            raise ReviewError("This review is already rejected.")
        return self._decide(review, ReviewStatus.REJECTED, note)

    def _decide(self, review, status, note):
        review.status = status
        review.moderation_note = note
        review.moderated_by = self.user
        review.moderated_at = timezone.now()
        review.save(update_fields=["status", "moderation_note", "moderated_by", "moderated_at"])
        return review


def pending_review_count():
    """Sidebar badge on "Reviews"."""
    return Review.objects.filter(status=ReviewStatus.PENDING).count()


@dataclass(frozen=True)
class RatingSummary:
    count: int
    average: Decimal | None
    distribution: list  # [(stars, count, percent)] from 5 down to 1

    @property
    def rounded(self):
        return int(self.average.to_integral_value(ROUND_HALF_UP)) if self.average is not None else 0


class ProductReviews:
    """Published reviews and their rating summary for one product page."""

    def __init__(self, product):
        self.product = product

    def published(self):
        return (Review.objects.published().for_product(self.product)
                .select_related("order_item__order__user", "order_item__variant__color",
                                "order_item__variant__size"))

    def summary(self):
        qs = Review.objects.published().for_product(self.product)
        stats = qs.aggregate(count=Count("id"), average=Avg("rating"))
        per_star = dict(qs.values_list("rating").annotate(n=Count("id")))
        total = stats["count"]
        average = (Decimal(str(stats["average"])).quantize(Decimal("0.1"), ROUND_HALF_UP)
                   if total else None)
        distribution = [(stars, per_star.get(stars, 0), round(per_star.get(stars, 0) * 100 / total) if total else 0)
                        for stars in range(5, 0, -1)]
        return RatingSummary(count=total, average=average, distribution=distribution)
