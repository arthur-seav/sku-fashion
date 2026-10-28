"""Payment operations after checkout (UC-08, UC-16, FR-S06, FR-X08)."""

from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Payment, Refund


class PaymentError(Exception):
    pass


class PaymentService:
    def __init__(self, user=None):
        self.user = user

    def upload_receipt(self, payment, image):
        """UC-08: the customer attaches a bank-transfer receipt."""
        if not payment.provider_obj.requires_receipt:
            raise PaymentError("This payment method does not take a receipt.")
        if payment.status != Payment.Status.PENDING:
            raise PaymentError("This payment is no longer awaiting a receipt.")
        if payment.receipt_image:
            payment.receipt_image.delete(save=False)
        payment.receipt_image = image
        payment.save(update_fields=["receipt_image"])
        return payment

    @transaction.atomic
    def reconcile(self, payment, transaction_ref=""):
        """UC-16 / DFD 6.6: Staff verify the transfer; the order advances to Paid."""
        from orders.models import OrderStatus
        from orders.workflow import OrderWorkflow

        payment = Payment.objects.select_for_update().select_related("order").get(pk=payment.pk)
        if payment.status != Payment.Status.PENDING:
            raise PaymentError(f"Payment is already {payment.get_status_display().lower()}.")
        if not payment.receipt_image:
            raise PaymentError("No receipt uploaded yet — nothing to reconcile against.")
        now = timezone.now()
        payment.status = Payment.Status.PAID
        payment.transaction_ref = transaction_ref or None
        payment.verified_by, payment.verified_at, payment.paid_at = self.user, now, now
        payment.save()
        if payment.order.status == OrderStatus.PENDING_PAYMENT:
            OrderWorkflow(payment.order, self.user).transition(OrderStatus.PAID, "Bank transfer reconciled")
        return payment

    def settle_cash_on_delivery(self, order):
        """FR-X08: a cash-on-delivery payment is marked Paid when the order is Completed."""
        now = timezone.now()
        return order.payments.filter(provider="COD", status=Payment.Status.PENDING).update(
            status=Payment.Status.PAID, paid_at=now, verified_by=self.user, verified_at=now)

    @transaction.atomic
    def refund(self, payment, amount, reason):
        """FR-S06: record a refund against a paid payment."""
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        amount = Decimal(amount)
        if payment.status != Payment.Status.PAID:
            raise PaymentError("Only paid payments can be refunded.")
        if amount <= 0:
            raise PaymentError("The refund amount must be positive.")
        if amount > payment.refundable_amount:
            raise PaymentError(f"At most {payment.refundable_amount} can still be refunded.")
        if not reason.strip():
            raise PaymentError("A reason is required.")
        return Refund.objects.create(payment=payment, amount=amount, reason=reason.strip(), user=self.user)
