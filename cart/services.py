"""Shopping cart rules (UC-05, FR-G04, FR-X02, FR-X03, FR-X06)."""

from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from catalog.models import ProductVariant

from .models import Cart, CartItem


class CartError(Exception):
    """A cart change was refused; the message is shown to the shopper."""


@dataclass
class PriceQuote:
    original: Decimal          # variant price before any campaign
    unit: Decimal              # price actually charged
    campaign: object = None    # promotions.Campaign applied, if any

    @property
    def discount(self):
        return self.original - self.unit


def list_price(variant):
    """Default pricer: no promotions."""
    return PriceQuote(original=variant.price, unit=variant.price)


@dataclass
class CartLine:
    item: CartItem
    quote: PriceQuote
    issue: str = ""            # why this line cannot be checked out as-is

    @property
    def variant(self):
        return self.item.variant

    @property
    def quantity(self):
        return self.item.quantity

    @property
    def original_total(self):
        return self.quote.original * self.quantity

    @property
    def line_total(self):
        return self.quote.unit * self.quantity


@dataclass
class CartSummary:
    lines: list = field(default_factory=list)

    @property
    def subtotal(self):
        return sum((line.original_total for line in self.lines), Decimal("0.00"))

    @property
    def discount(self):
        return self.subtotal - self.total

    @property
    def total(self):
        return sum((line.line_total for line in self.lines), Decimal("0.00"))

    @property
    def item_count(self):
        return sum(line.quantity for line in self.lines)

    @property
    def issues(self):
        return [line for line in self.lines if line.issue]

    @property
    def is_empty(self):
        return not self.lines


class CartService:
    SESSION_KEY = "cart_id"

    def __init__(self, request, pricer=None):
        self.request = request
        self.pricer = pricer or self.default_pricer()

    @staticmethod
    def default_pricer():
        return list_price

    # ---- cart lookup ---------------------------------------------------
    def get_cart(self, create=False):
        user = self.request.user
        if user.is_authenticated:
            cart = Cart.objects.filter(user=user).first()
            if cart is None and create:
                cart = Cart.objects.create(user=user)
            return cart
        cart_id = self.request.session.get(self.SESSION_KEY)
        cart = Cart.objects.filter(pk=cart_id, user__isnull=True).first() if cart_id else None
        if cart is None and create:
            if not self.request.session.session_key:
                self.request.session.save()
            cart = Cart.objects.create(session_key=self.request.session.session_key)
            self.request.session[self.SESSION_KEY] = cart.pk
        return cart

    def _items(self, cart):
        return cart.items.select_related("variant__product__category", "variant__color", "variant__size")\
            .prefetch_related("variant__product__images")

    # ---- changes ---------------------------------------------------------
    @transaction.atomic
    def add(self, variant, quantity=1):
        if quantity < 1:
            raise CartError("Quantity must be at least 1.")
        variant = ProductVariant.objects.select_related("product").get(pk=variant.pk)
        if not (variant.is_active and variant.product.is_active):
            raise CartError("This item is no longer available.")
        if variant.is_sold_out:
            raise CartError(f"{variant.product.name} ({variant.spec}) is sold out.")
        cart = self.get_cart(create=True)
        item, created = CartItem.objects.get_or_create(cart=cart, variant=variant, defaults={"quantity": 0})
        wanted = item.quantity + quantity
        if wanted > variant.stock_qty:
            already = f" You already have {item.quantity} in your cart." if item.quantity else ""
            raise CartError(f"Only {variant.stock_qty} of {variant.product.name} ({variant.spec}) "
                            f"available.{already}")
        item.quantity = wanted
        item.save(update_fields=["quantity"])
        return item

    def update(self, item_id, quantity):
        item = self._own_item(item_id)
        if quantity <= 0:
            item.delete()
            return None
        if quantity > item.variant.stock_qty:
            raise CartError(f"Only {item.variant.stock_qty} of {item.variant.product.name} "
                            f"({item.variant.spec}) available.")
        item.quantity = quantity
        item.save(update_fields=["quantity"])
        return item

    def remove(self, item_id):
        self._own_item(item_id).delete()

    def clear(self):
        cart = self.get_cart()
        if cart:
            cart.items.all().delete()

    def _own_item(self, item_id):
        cart = self.get_cart()
        item = (CartItem.objects.select_related("variant__product").filter(cart=cart, pk=item_id).first()
                if cart else None)
        if item is None:
            raise CartError("That item is not in your cart.")
        return item

    # ---- reading ---------------------------------------------------------
    def summary(self):
        """Lines priced with the current prices and checked against current
        stock (FR-X03): a line that can no longer be bought carries an issue."""
        cart = self.get_cart()
        if cart is None:
            return CartSummary()
        lines = []
        for item in self._items(cart):
            v = item.variant
            issue = ""
            if not (v.is_active and v.product.is_active):
                issue = "No longer available — please remove it."
            elif v.is_sold_out:
                issue = "Sold out — please remove it."
            elif item.quantity > v.stock_qty:
                issue = f"Only {v.stock_qty} left — reduce the quantity."
            lines.append(CartLine(item=item, quote=self.pricer(v), issue=issue))
        return CartSummary(lines=lines)

    def count(self):
        cart = self.get_cart()
        if cart is None:
            return 0
        return sum(cart.items.values_list("quantity", flat=True))

    # ---- guest → customer (FR-X02) --------------------------------------------
    @staticmethod
    @transaction.atomic
    def merge_guest_cart(guest_cart_id, user):
        guest = Cart.objects.filter(pk=guest_cart_id, user__isnull=True).first()
        if guest is None:
            return None
        cart, _ = Cart.objects.get_or_create(user=user)
        for guest_item in guest.items.select_related("variant"):
            item, _ = CartItem.objects.get_or_create(cart=cart, variant=guest_item.variant,
                                                     defaults={"quantity": 0})
            # Combine quantities but never beyond what is in stock. A sold-out
            # line is kept so the cart can tell the shopper what happened.
            combined = item.quantity + guest_item.quantity
            stock = guest_item.variant.stock_qty
            item.quantity = min(combined, stock) if stock > 0 else combined
            item.save(update_fields=["quantity"])
        guest.delete()
        return cart
