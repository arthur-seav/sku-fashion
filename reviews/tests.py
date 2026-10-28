"""Product reviews: UC-22 Write a Review (FR-C08), UC-23 Moderate Reviews (FR-S12)."""

from django.urls import reverse

from core.navigation import badges
from core.testing import PASSWORD, make_staff, make_user
from orders.models import Order, OrderStatus
from orders.tests import CheckoutTestCase
from orders.workflow import OrderWorkflow
from shipping.services import ShipmentService

from .models import Review, ReviewStatus
from .services import ProductReviews, ReviewError, ReviewModerationService, ReviewService


class ReviewTestCase(CheckoutTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()

    def order(self, complete=True):
        """A cash-on-delivery order for v1, walked to Completed (or left in Preparing)."""
        self.add(self.v1, 1)
        self.place()
        order = Order.objects.latest("placed_at")
        if complete:
            ShipmentService(self.staff).create(order, "J&T Express", "TRK1")
            OrderWorkflow(order, self.staff).transition(OrderStatus.COMPLETED)
        order.refresh_from_db()
        return order

    def item(self, **kw):
        return self.order(**kw).items.get()

    def write(self, item, rating=5, comment="Great fit"):
        return self.client.post(reverse("reviews:write", args=[item.pk]), {"rating": rating, "comment": comment})


class WriteReviewTests(ReviewTestCase):
    """UC-22 / FR-C08."""

    def test_completed_order_item_can_be_reviewed_and_waits_for_moderation(self):
        item = self.item()
        response = self.write(item, 4, "  Soft linen, runs a bit large.  ")
        self.assertRedirects(response, reverse("reviews:my_reviews"))
        review = Review.objects.get()
        self.assertEqual((review.order_item, review.rating, review.status), (item, 4, ReviewStatus.PENDING))
        self.assertEqual(review.comment, "Soft linen, runs a bit large.")

    def test_order_not_completed_cannot_be_reviewed(self):
        item = self.item(complete=False)
        response = self.write(item)
        self.assertRedirects(response, reverse("orders:order_detail", args=[item.order.order_no]))
        self.assertFalse(Review.objects.exists())
        with self.assertRaisesMessage(ReviewError, "once order"):
            ReviewService(self.customer).submit(item, 5)

    def test_cannot_review_someone_elses_item(self):
        item = self.item()
        other = make_user("other@example.com")
        self.client.force_login(other)
        self.assertEqual(self.write(item).status_code, 404)
        with self.assertRaisesMessage(ReviewError, "your own orders"):
            ReviewService(other).submit(item, 5)

    def test_staff_cannot_use_the_customer_review_page(self):
        item = self.item()
        self.client.force_login(self.staff)
        self.assertEqual(self.write(item).status_code, 403)

    def test_rating_is_required_and_must_be_1_to_5(self):
        item = self.item()
        for bad in ["", "0", "6", "abc"]:
            response = self.write(item, bad)
            self.assertEqual(response.status_code, 200, bad)
        self.assertFalse(Review.objects.exists())
        with self.assertRaisesMessage(ReviewError, "1 to 5"):
            ReviewService(self.customer).submit(item, 9)

    def test_comment_is_optional(self):
        item = self.item()
        self.write(item, 3, "")
        self.assertEqual(Review.objects.get().comment, "")

    def test_one_review_per_item_editing_keeps_the_same_review(self):
        item = self.item()
        self.write(item, 2, "First")
        self.write(item, 3, "Second thoughts")
        review = Review.objects.get()
        self.assertEqual((review.rating, review.comment), (3, "Second thoughts"))

    def test_published_review_can_no_longer_be_changed(self):
        item = self.item()
        self.write(item)
        ReviewModerationService(self.staff).approve(Review.objects.get())
        response = self.write(item, 1, "Changed")
        self.assertRedirects(response, reverse("orders:order_detail", args=[item.order.order_no]))
        self.assertEqual(Review.objects.get().rating, 5)

    def test_rejected_review_can_be_edited_and_goes_back_to_pending(self):
        item = self.item()
        self.write(item, 1, "Rubbish, call 012 345 678 for a better shop")
        ReviewModerationService(self.staff).reject(Review.objects.get(), "Contains a phone number")
        page = self.client.get(reverse("reviews:write", args=[item.pk]))
        self.assertContains(page, "Contains a phone number")
        self.write(item, 2, "Seams came apart after one wash")
        review = Review.objects.get()
        self.assertEqual(review.status, ReviewStatus.PENDING)
        self.assertEqual((review.moderation_note, review.moderated_by), ("", None))

    def test_each_purchased_item_is_reviewed_separately(self):
        """The ERD ties a review to an order item, so buying again means another review."""
        first, second = self.item(), self.item()
        self.write(first, 5)
        self.write(second, 4)
        self.assertEqual(Review.objects.count(), 2)

    def test_my_reviews_lists_items_still_to_review(self):
        item = self.item()
        page = self.client.get(reverse("reviews:my_reviews"))
        self.assertContains(page, reverse("reviews:write", args=[item.pk]))
        self.write(item)
        page = self.client.get(reverse("reviews:my_reviews"))
        self.assertContains(page, "Nothing to review")
        self.assertContains(page, "Awaiting check")

    def test_order_detail_offers_review_only_once_completed(self):
        pending = self.item(complete=False)
        page = self.client.get(reverse("orders:order_detail", args=[pending.order.order_no]))
        self.assertNotContains(page, "Write a review")
        done = self.item()
        page = self.client.get(reverse("orders:order_detail", args=[done.order.order_no]))
        self.assertContains(page, reverse("reviews:write", args=[done.pk]))


class ModerationTests(ReviewTestCase):
    """UC-23 / FR-S12."""

    def setUp(self):
        super().setUp()
        self.review_item = self.item()
        self.write(self.review_item, 4, "Nice shirt")
        self.review = Review.objects.get()
        self.product_url = reverse("catalog:product_detail", args=[self.product.slug])

    def moderate(self, action, **data):
        self.client.force_login(self.staff)
        return self.client.post(reverse("reviews_bo:review_moderate", args=[self.review.pk, action]), data)

    def test_pending_review_is_not_shown_on_the_product_page(self):
        page = self.client.get(self.product_url)
        self.assertNotContains(page, "Nice shirt")
        self.assertContains(page, "No reviews yet")

    def test_approve_publishes_with_rating_summary(self):
        self.moderate("approve")
        self.review.refresh_from_db()
        self.assertEqual(self.review.status, ReviewStatus.APPROVED)
        self.assertEqual(self.review.moderated_by, self.staff)
        self.assertIsNotNone(self.review.moderated_at)
        page = self.client.get(self.product_url)
        self.assertContains(page, "Nice shirt")
        self.assertContains(page, "Test U.")           # first name + last initial only
        self.assertContains(page, "Verified purchase")

    def test_summary_averages_published_reviews_only(self):
        ReviewModerationService(self.staff).approve(self.review)             # 4
        second = self.item()
        ReviewModerationService(self.staff).approve(ReviewService(self.customer).submit(second, 5))
        third = self.item()
        ReviewService(self.customer).submit(third, 1)                        # still pending
        summary = ProductReviews(self.product).summary()
        self.assertEqual(summary.count, 2)
        self.assertEqual(str(summary.average), "4.5")
        self.assertEqual(summary.distribution[0], (5, 1, 50))
        self.assertEqual(summary.distribution[-1], (1, 0, 0))

    def test_reject_requires_a_reason(self):
        response = self.moderate("reject", note="  ")
        self.assertEqual(Review.objects.get().status, ReviewStatus.PENDING)
        self.assertContains(self.client.get(response.url), "Give a reason")

    def test_reject_records_reason_and_moderator(self):
        self.moderate("reject", note="Off-topic")
        self.review.refresh_from_db()
        self.assertEqual((self.review.status, self.review.moderation_note, self.review.moderated_by),
                         (ReviewStatus.REJECTED, "Off-topic", self.staff))

    def test_published_review_can_be_unpublished(self):
        self.moderate("approve")
        self.moderate("reject", note="Reported as fake")
        self.assertEqual(Review.objects.get().status, ReviewStatus.REJECTED)
        self.assertNotContains(self.client.get(self.product_url), "Nice shirt")

    def test_approving_twice_is_reported(self):
        ReviewModerationService(self.staff).approve(self.review)
        with self.assertRaisesMessage(ReviewError, "already published"):
            ReviewModerationService(self.staff).approve(self.review)

    def test_queue_opens_on_pending_oldest_first_and_filters(self):
        later = self.item()
        ReviewService(self.customer).submit(later, 2, "Faded quickly")
        self.client.force_login(self.staff)
        page = self.client.get(reverse("reviews_bo:review_list"))
        reviews = list(page.context["reviews"])
        self.assertEqual([r.comment for r in reviews], ["Nice shirt", "Faded quickly"])
        page = self.client.get(reverse("reviews_bo:review_list"), {"rating": 2})
        self.assertEqual([r.comment for r in page.context["reviews"]], ["Faded quickly"])
        page = self.client.get(reverse("reviews_bo:review_list"), {"status": "APPROVED"})
        self.assertEqual(list(page.context["reviews"]), [])

    def test_moderation_redirects_back_to_the_filtered_list_only_on_this_site(self):
        target = reverse("reviews_bo:review_list") + "?status=PENDING&rating=4"
        self.assertRedirects(self.moderate("approve", next=target), target)
        self.moderate("reject", note="x", next="https://evil.example.com/")
        self.assertRedirects(self.moderate("approve", next="https://evil.example.com/"),
                             reverse("reviews_bo:review_list"))

    def test_sidebar_badge_counts_pending_reviews(self):
        self.assertEqual(badges.value("reviews_pending"), 1)
        ReviewModerationService(self.staff).approve(self.review)
        self.assertEqual(badges.value("reviews_pending"), 0)

    def test_customers_cannot_moderate(self):
        self.client.login(email="buyer@example.com", password=PASSWORD)
        response = self.client.post(reverse("reviews_bo:review_moderate", args=[self.review.pk, "approve"]))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get(reverse("reviews_bo:review_list")).status_code, 403)
        self.assertEqual(Review.objects.get().status, ReviewStatus.PENDING)
