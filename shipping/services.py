"""Delivery fee quotes (DFD 6.7 Quote Shipping Fee, UC-07 step 4)."""

from dataclasses import dataclass
from decimal import Decimal

from core.money import ZERO

from .models import ShippingMethod, ShippingRate


@dataclass
class ShippingQuote:
    method: ShippingMethod
    fee: Decimal
    reason: str  # "free threshold", "province rate", "base fee"


class ShippingQuoteService:
    @staticmethod
    def active_methods():
        return ShippingMethod.objects.filter(is_active=True)

    def quote(self, method, province, amount):
        """Find method → look up province rate → apply free threshold."""
        if method.free_threshold is not None and amount >= method.free_threshold:
            return ShippingQuote(method, ZERO, "free threshold")
        rate = ShippingRate.objects.filter(method=method, province=province).first()
        if rate is not None:
            return ShippingQuote(method, rate.fee, "province rate")
        return ShippingQuote(method, method.base_fee, "base fee")


class ShipmentError(Exception):
    pass


class ShipmentService:
    """UC-17: hand an order to a carrier; delivery confirmation."""

    def __init__(self, user=None):
        self.user = user

    def create(self, order, carrier, tracking_no):
        from django.db import transaction
        from django.utils import timezone

        from orders.models import Order, OrderStatus
        from orders.workflow import OrderWorkflow

        from .models import Shipment

        if not carrier.strip() or not tracking_no.strip():
            raise ShipmentError("Carrier and tracking number are both required.")
        with transaction.atomic():
            # Re-read under a row lock: the caller's instance may be stale.
            order = Order.objects.select_for_update().get(pk=order.pk)
            if order.status != OrderStatus.PREPARING:
                raise ShipmentError(f"Only orders in Preparing can be shipped (this one is "
                                    f"{order.get_status_display()}).")
            shipment = Shipment.objects.create(order=order, carrier=carrier.strip(), tracking_no=tracking_no.strip(),
                                               shipped_at=timezone.now())
            OrderWorkflow(order, self.user).transition(
                OrderStatus.SHIPPED, f"{shipment.carrier} · tracking {shipment.tracking_no}")  # FR-X08
        return shipment

    def mark_delivered(self, shipment):
        from django.utils import timezone

        shipment.status, shipment.delivered_at = shipment.Status.DELIVERED, timezone.now()
        shipment.save(update_fields=["status", "delivered_at"])
        return shipment
