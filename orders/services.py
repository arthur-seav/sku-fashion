"""Checkout (UC-07 Place an Order).

    quote()        steps 4–6: shipping fee, coupon discount, VAT on the discounted subtotal
    snapshot()     the unit prices the customer was shown on the checkout page
    place_order()  steps 1 + 9: re-validate, then one transaction for everything (FR-X05)
"""

from dataclasses import dataclass
from decimal import Decimal

from django.conf import settings
from django.db import transaction

from core.money import ZERO, to_money
from inventory.services import InventoryService
from payments.providers import registry
from promotions.services import CouponError, CouponService
from shipping.services import ShippingQuoteService

from .models import Order, OrderItem, OrderStatusHistory


class CheckoutError(Exception):
    """Checkout cannot continue; the customer is sent back to the cart."""


@dataclass
class CheckoutTotals:
    subtotal: Decimal            # list prices × quantities
    campaign_discount: Decimal
    coupon_discount: Decimal
    shipping_fee: Decimal
    tax: Decimal
    shipping_reason: str = ""

    @property
    def discount_total(self):
        return self.campaign_discount + self.coupon_discount

    @property
    def taxable(self):
        """Discounted subtotal — the base for VAT (FR-X04)."""
        return self.subtotal - self.discount_total

    @property
    def grand_total(self):
        return self.taxable + self.tax + self.shipping_fee


class CheckoutService:
    def __init__(self, user, cart_service, tax_rate=None, coupons=None, shipping=None, inventory=None):
        self.user = user
        self.cart = cart_service
        self.tax_rate = settings.STORE_TAX_RATE if tax_rate is None else tax_rate
        self.coupons = coupons or CouponService()
        self.shipping = shipping or ShippingQuoteService()
        self.inventory = inventory or InventoryService(user)

    # ---- pricing ---------------------------------------------------------------
    def quote(self, summary, shipping_method=None, province="", coupon=None):
        merchandise = summary.total  # after campaign prices
        coupon_discount = coupon.discount_on(merchandise) if coupon else ZERO
        taxable = merchandise - coupon_discount
        fee, reason = ZERO, ""
        if shipping_method is not None:
            q = self.shipping.quote(shipping_method, province, taxable)
            fee, reason = q.fee, q.reason
        return CheckoutTotals(
            subtotal=summary.subtotal,
            campaign_discount=summary.discount,
            coupon_discount=coupon_discount,
            shipping_fee=fee,
            tax=to_money(taxable * self.tax_rate),
            shipping_reason=reason,
        )

    def apply_coupon(self, code, summary):
        """Returns the coupon or raises CouponError with the specific reason."""
        return self.coupons.validate(code, self.user, summary.total)

    @staticmethod
    def snapshot(summary):
        return {str(line.variant.pk): [line.quantity, str(line.quote.unit)] for line in summary.lines}

    # ---- validation (UC-07 step 1) --------------------------------------------
    def validate_cart(self, summary, shown_prices=None):
        if summary.is_empty:
            raise CheckoutError("Your cart is empty.")
        for line in summary.lines:
            label = f"{line.variant.product.name} ({line.variant.spec})"
            if line.issue:
                raise CheckoutError(f"{label}: {line.issue}")
            if shown_prices is not None:
                shown = shown_prices.get(str(line.variant.pk))
                if shown is None or shown[0] != line.quantity:
                    raise CheckoutError("Your cart changed while you were checking out. Please review it.")
                if Decimal(shown[1]) != line.quote.unit:
                    raise CheckoutError(f"The price of {label} changed from {shown[1]} to {line.quote.unit}. "
                                        f"Please review your cart.")

    # ---- the transaction (UC-07 step 9) ------------------------------------------
    def place_order(self, *, address, shipping_method, provider_code, coupon_code="", shown_prices=None):
        provider = registry.get(provider_code)
        with transaction.atomic():
            summary = self.cart.summary()
            self.validate_cart(summary, shown_prices)
            coupon = None
            if coupon_code:
                try:
                    coupon = self.apply_coupon(coupon_code, summary)
                except CouponError as exc:
                    raise CheckoutError(str(exc)) from exc
            totals = self.quote(summary, shipping_method, address["province"], coupon)

            order = Order.objects.create(
                order_no=Order.generate_order_no(),
                user=self.user,
                status=provider.initial_order_status,
                subtotal=totals.subtotal,
                discount_total=totals.discount_total,
                tax_total=totals.tax,
                shipping_fee=totals.shipping_fee,
                grand_total=totals.grand_total,
                currency=settings.STORE_CURRENCY,
                ship_recipient=address["recipient"],
                ship_phone=address["phone"],
                ship_province=address["province"],
                ship_district=address["district"],
                ship_line_1=address["line_1"],
                shipping_method=shipping_method,
            )
            for line in summary.lines:
                v = line.variant
                OrderItem.objects.create(
                    order=order, variant=v, campaign=line.quote.campaign,
                    product_name=v.product.name, variant_spec=f"{v.spec} · {v.sku}",
                    original_price=line.quote.original, unit_price=line.quote.unit,
                    quantity=line.quantity, line_total=line.line_total,
                )
                # Raises InsufficientStock if another order took the stock first;
                # the whole transaction then rolls back (FR-X05, FR-X06).
                self.inventory.deduct(v, line.quantity, order.order_no)
            provider.create_payment(order)
            if coupon:
                self.coupons.redeem(coupon, order, totals.coupon_discount)
            OrderStatusHistory.objects.create(order=order, from_status="", to_status=order.status,
                                              user=self.user, note=f"Order placed · {provider.label}")
            self.cart.clear()
        return order
