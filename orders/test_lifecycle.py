"""Order lifecycle: UC-08, UC-10, UC-15, UC-16, UC-17, FR-X07–X09."""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from core.navigation import badges
from core.testing import make_staff
from inventory.models import StockMovement
from payments.models import Payment
from payments.services import PaymentError, PaymentService
from promotions.models import Coupon, DiscountType
from shipping.services import ShipmentService

from .models import Order, OrderStatus
from .tests import CheckoutTestCase
from .workflow import InvalidTransition, OrderWorkflow


def tiny_png():
    import base64
    data = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    return SimpleUploadedFile("receipt.png", data, content_type="image/png")


@override_settings(MEDIA_ROOT="/home/hermes/.hermes/cache/scratch/sku-media-test")
class LifecycleTestCase(CheckoutTestCase):
    def setUp(self):
        super().setUp()
        self.staff = make_staff()

    def order(self, payment="COD", qty=2, **form):
        self.add(self.v1, qty)
        self.place(payment_method=payment, **form)
        return Order.objects.latest("placed_at")


class TransitionTests(LifecycleTestCase):
    def test_transition_not_in_table_is_rejected_with_allowed_list(self):
        order = self.order("BANK_TRANSFER")
        with self.assertRaisesMessage(InvalidTransition, "Allowed next: Paid, Cancelled"):
            OrderWorkflow(order, self.staff).transition(OrderStatus.COMPLETED)

    def test_paid_only_through_reconciliation(self):
        order = self.order("BANK_TRANSFER")
        with self.assertRaisesMessage(InvalidTransition, "Reconcile"):
            OrderWorkflow(order, self.staff).transition(OrderStatus.PAID)

    def test_shipped_requires_shipment(self):
        order = self.order()
        with self.assertRaisesMessage(InvalidTransition, "Create a shipment"):
            OrderWorkflow(order, self.staff).transition(OrderStatus.SHIPPED)

    def test_full_bank_transfer_flow(self):
        order = self.order("BANK_TRANSFER")
        payment = order.payment
        with self.assertRaisesMessage(PaymentError, "No receipt"):
            PaymentService(self.staff).reconcile(payment)

        # UC-08: customer uploads the receipt.
        self.client.post(reverse("orders:upload_receipt", args=[order.order_no]), {"receipt": tiny_png()})
        payment.refresh_from_db()
        self.assertTrue(payment.receipt_image)
        self.assertEqual(badges.value("orders_awaiting"), 1)

        # UC-16: staff reconcile → payment Paid, order Paid.
        self.client.force_login(self.staff)
        self.client.post(reverse("orders_bo:order_action", args=[order.order_no, "reconcile"]),
                         {"payment": payment.pk, "transaction_ref": "ABA-778899"})
        payment.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual((payment.status, payment.verified_by, payment.transaction_ref),
                         ("PAID", self.staff, "ABA-778899"))
        self.assertEqual(order.status, OrderStatus.PAID)

        # Paid → Preparing → (shipment) Shipped → Completed.
        self.client.post(reverse("orders_bo:order_action", args=[order.order_no, "transition"]),
                         {"to": "PREPARING"})
        self.client.post(reverse("orders_bo:order_action", args=[order.order_no, "ship"]),
                         {"carrier": "J&T Express", "tracking_no": "JT123"})
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.SHIPPED)
        self.client.post(reverse("orders_bo:order_action", args=[order.order_no, "transition"]),
                         {"to": "COMPLETED"})
        order.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.COMPLETED)
        self.assertIsNotNone(order.shipment.delivered_at)

        # Every step is in the history with its operator (FR-X07).
        steps = list(order.history.values_list("from_status", "to_status"))
        self.assertEqual(steps, [("", "PENDING_PAYMENT"), ("PENDING_PAYMENT", "PAID"), ("PAID", "PREPARING"),
                                 ("PREPARING", "SHIPPED"), ("SHIPPED", "COMPLETED")])
        self.assertEqual(order.history.last().user, self.staff)

    def test_cod_payment_marked_paid_on_completion(self):
        order = self.order()
        ShipmentService(self.staff).create(order, "Grab Express", "G-1")
        OrderWorkflow(order, self.staff).transition(OrderStatus.COMPLETED)
        self.assertEqual(Payment.objects.get(order=order).status, "PAID")  # FR-X08

    def test_customer_sees_tracking(self):
        order = self.order()
        ShipmentService(self.staff).create(order, "VET Express", "VET-42")
        page = self.client.get(reverse("orders:order_detail", args=[order.order_no]))
        self.assertContains(page, "VET-42")

    def test_shipment_uses_current_status_not_a_stale_instance(self):
        """Regression: the caller's order object can be out of date (found by seed_demo)."""
        order = self.order("BANK_TRANSFER")
        stale = Order.objects.get(pk=order.pk)               # still Pending Payment in memory
        PaymentService(self.customer).upload_receipt(order.payment, tiny_png())
        PaymentService(self.staff).reconcile(order.payment)
        OrderWorkflow(order, self.staff).transition(OrderStatus.PREPARING)
        ShipmentService(self.staff).create(stale, "J&T Express", "JT-9")
        self.assertEqual(Order.objects.get(pk=order.pk).status, OrderStatus.SHIPPED)

    def test_receipt_rejected_for_cash_on_delivery(self):
        order = self.order()
        response = self.client.post(reverse("orders:upload_receipt", args=[order.order_no]),
                                    {"receipt": tiny_png()}, follow=True)
        self.assertContains(response, "does not take a receipt")


class CancellationTests(LifecycleTestCase):
    """UC-10."""

    def test_customer_cancel_restores_stock_coupon_and_payment(self):
        start = timezone.now() - timedelta(days=1)
        coupon = Coupon.objects.create(code="ONE", discount_type=DiscountType.FIXED, discount_value=Decimal("2"),
                                       usage_limit=1, start_at=start, end_at=start + timedelta(days=3))
        order = self.order(coupon_code="ONE")
        self.assertEqual(coupon.used_count, 1)
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.stock_qty, 3)

        self.client.post(reverse("orders:order_cancel", args=[order.order_no]))
        order.refresh_from_db()
        self.v1.refresh_from_db()
        self.assertEqual(order.status, OrderStatus.CANCELLED)
        self.assertEqual(self.v1.stock_qty, 5)
        self.assertTrue(StockMovement.objects.filter(reference=order.order_no, type="IN", quantity=2).exists())
        self.assertEqual(coupon.used_count, 0)                     # usage count decremented
        self.assertEqual(order.payment.status, "CANCELLED")
        self.assertEqual(order.history.last().user, self.customer)

    def test_shipped_order_cannot_be_cancelled(self):
        order = self.order()
        ShipmentService(self.staff).create(order, "Grab Express", "G-2")
        with self.assertRaisesMessage(InvalidTransition, "handled as returns"):
            OrderWorkflow(order, self.customer).cancel()

    def test_cancelling_paid_order_then_refund(self):
        order = self.order("BANK_TRANSFER")
        PaymentService(self.customer).upload_receipt(order.payment, tiny_png())
        PaymentService(self.staff).reconcile(order.payment)
        OrderWorkflow(order, self.staff).cancel("Customer called")
        order.refresh_from_db()
        self.assertIn("refund to be issued", order.history.last().note)
        payment = order.payment
        self.assertEqual(payment.status, "PAID")  # money was received; refund is separate
        with self.assertRaisesMessage(PaymentError, "At most"):
            PaymentService(self.staff).refund(payment, payment.amount + 1, "Too much")
        refund = PaymentService(self.staff).refund(payment, payment.amount, "Order cancelled")
        self.assertEqual(refund.user, self.staff)
        self.assertEqual(payment.refundable_amount, 0)


class AutoCancelTests(LifecycleTestCase):
    """FR-X09: unpaid bank transfers cancelled after 24 h; COD exempt."""

    def test_command_cancels_only_old_unpaid_bank_transfers(self):
        old_bank = self.order("BANK_TRANSFER", qty=1)
        fresh_bank = self.order("BANK_TRANSFER", qty=1)
        old_cod = self.order("COD", qty=1)
        long_ago = timezone.now() - timedelta(hours=25)
        Order.objects.filter(pk__in=[old_bank.pk, old_cod.pk]).update(placed_at=long_ago)

        out = StringIO()
        call_command("cancel_unpaid_orders", stdout=out)
        self.assertIn(old_bank.order_no, out.getvalue())

        statuses = dict(Order.objects.values_list("pk", "status"))
        self.assertEqual(statuses[old_bank.pk], OrderStatus.CANCELLED)
        self.assertEqual(statuses[fresh_bank.pk], OrderStatus.PENDING_PAYMENT)
        self.assertEqual(statuses[old_cod.pk], OrderStatus.PREPARING)
        entry = Order.objects.get(pk=old_bank.pk).history.last()
        self.assertIsNone(entry.user)  # the system is the operator
        self.v1.refresh_from_db()
        self.assertEqual(self.v1.stock_qty, 3)  # 5 − 1 − 1 − 1 + 1 restored

    def test_order_with_uploaded_receipt_is_kept_and_dry_run_changes_nothing(self):
        with_receipt = self.order("BANK_TRANSFER", qty=1)
        unpaid = self.order("BANK_TRANSFER", qty=1)
        PaymentService(self.customer).upload_receipt(with_receipt.payment, tiny_png())
        Order.objects.update(placed_at=timezone.now() - timedelta(hours=30))

        out = StringIO()
        call_command("cancel_unpaid_orders", "--dry-run", stdout=out)
        self.assertIn(f"Would cancel 1 order(s): {unpaid.order_no}", out.getvalue())
        self.assertFalse(Order.objects.filter(status=OrderStatus.CANCELLED).exists())

        call_command("cancel_unpaid_orders", stdout=StringIO())
        statuses = dict(Order.objects.values_list("pk", "status"))
        self.assertEqual(statuses[with_receipt.pk], OrderStatus.PENDING_PAYMENT)  # waiting for Staff
        self.assertEqual(statuses[unpaid.pk], OrderStatus.CANCELLED)


class BackofficeOrderViewTests(LifecycleTestCase):
    def test_list_filters_and_detail_render(self):
        order = self.order("BANK_TRANSFER")
        self.client.force_login(self.staff)
        listing = self.client.get(reverse("orders_bo:order_list"), {"status": "PENDING_PAYMENT", "q": "buyer@"})
        self.assertContains(listing, order.order_no)
        self.assertNotContains(self.client.get(reverse("orders_bo:order_list"), {"status": "SHIPPED"}),
                               order.order_no)
        detail = self.client.get(reverse("orders_bo:order_detail", args=[order.order_no]))
        self.assertContains(detail, "Waiting for the customer to upload a receipt")

    def test_invalid_action_shows_error(self):
        order = self.order()
        self.client.force_login(self.staff)
        response = self.client.post(reverse("orders_bo:order_action", args=[order.order_no, "transition"]),
                                    {"to": "COMPLETED"}, follow=True)
        self.assertContains(response, "Allowed next")
