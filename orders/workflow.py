"""Order status workflow (UC-10 Cancel an Order, UC-15 Process an Order, FR-X07–X09).

Every status change goes through `OrderWorkflow`, which
  1. locks the order row,
  2. checks the transition against the permitted-transition table,
  3. applies the side effects (stock, coupon, payment),
  4. writes one OrderStatusHistory row with operator and time.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from inventory.services import InventoryService
from promotions.services import CouponService

from .models import Order, OrderStatus, OrderStatusHistory


class InvalidTransition(Exception):
    pass


class OrderWorkflow:
    def __init__(self, order, user=None):
        self.order = order
        self.user = user  # None = the system acted (e.g. auto-cancel)

    # ---- generic transition (UC-15 steps 3–5) ---------------------------------
    @transaction.atomic
    def transition(self, to_status, note=""):
        order = self._lock()
        to_status = OrderStatus(to_status)
        if to_status == OrderStatus.CANCELLED:
            return self.cancel(note)
        if not order.can_transition_to(to_status):
            allowed = ", ".join(s.label for s in order.allowed_transitions()) or "none"
            raise InvalidTransition(f"Cannot change {order.order_no} from {order.get_status_display()} to "
                                    f"{to_status.label}. Allowed next: {allowed}.")
        payment = order.payment
        if to_status == OrderStatus.PAID and (payment is None or payment.status != payment.Status.PAID):
            raise InvalidTransition("Reconcile the bank-transfer payment first; that moves the order to Paid.")
        if to_status == OrderStatus.SHIPPED and not hasattr(order, "shipment"):
            raise InvalidTransition("Create a shipment with carrier and tracking number first (UC-15 3a).")
        if to_status == OrderStatus.COMPLETED:
            self._on_completed(order)
        return self._set_status(order, to_status, note)

    # ---- cancellation (UC-10) ------------------------------------------------------
    @transaction.atomic
    def cancel(self, note=""):
        order = self._lock()
        if not order.is_cancellable:
            if order.status in (OrderStatus.SHIPPED, OrderStatus.COMPLETED):
                raise InvalidTransition(f"Order {order.order_no} has already been "
                                        f"{order.get_status_display().lower()}. Shipped orders are handled "
                                        f"as returns, which are not available in this release.")
            raise InvalidTransition(f"Order {order.order_no} is already cancelled.")
        was_paid = any(p.status == p.Status.PAID for p in order.payments.all())

        inventory = InventoryService(self.user)
        for item in order.items.select_related("variant"):
            inventory.restore(item.variant, item.quantity, order.order_no)   # IN movement, order ref
        CouponService().release(order)                                        # usage count goes back
        order.payments.filter(status="PENDING").update(status="CANCELLED")

        if was_paid:
            note = (note + " " if note else "") + "Paid — refund to be issued by staff."
        return self._set_status(order, OrderStatus.CANCELLED, note.strip())

    @classmethod
    def cancel_expired(cls, hours=None, now=None, dry_run=False):
        """FR-X09: bank-transfer orders unpaid for over 24 h are cancelled.
        Cash-on-delivery orders never sit in Pending Payment, so they are exempt.
        Orders whose customer already uploaded a receipt are kept: the money has
        been sent and is only waiting for Staff to reconcile it."""
        hours = settings.UNPAID_ORDER_TIMEOUT_HOURS if hours is None else hours
        cutoff = (now or timezone.now()) - timedelta(hours=hours)
        expired = (Order.objects.filter(status=OrderStatus.PENDING_PAYMENT, placed_at__lt=cutoff,
                                        payments__provider="BANK_TRANSFER", payments__status="PENDING")
                   .exclude(payments__receipt_image__gt="").distinct().order_by("placed_at"))
        if dry_run:
            return [o.order_no for o in expired]
        cancelled = []
        for order in expired:
            cls(order, user=None).cancel(f"Automatically cancelled: unpaid for over {hours} hours.")
            cancelled.append(order.order_no)
        return cancelled

    # ---- helpers ---------------------------------------------------------------------
    def _lock(self):
        self.order = Order.objects.select_for_update().get(pk=self.order.pk)
        return self.order

    def _on_completed(self, order):
        from payments.services import PaymentService
        PaymentService(self.user).settle_cash_on_delivery(order)   # FR-X08: COD paid on completion
        shipment = getattr(order, "shipment", None)
        if shipment is not None and shipment.delivered_at is None:
            shipment.status, shipment.delivered_at = shipment.Status.DELIVERED, timezone.now()
            shipment.save(update_fields=["status", "delivered_at"])

    def _set_status(self, order, to_status, note):
        previous = order.status
        order.status = to_status
        order.save(update_fields=["status", "updated_at"])
        OrderStatusHistory.objects.create(order=order, from_status=previous, to_status=to_status,
                                          user=self.user, note=note)
        return order
