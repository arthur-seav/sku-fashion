from django.test import TestCase
from django.urls import reverse

from core.testing import PASSWORD, make_user, make_variant

from .models import Cart, CartItem


class CartTests(TestCase):
    """UC-05 / FR-G04 / FR-X06."""

    def setUp(self):
        self.variant = make_variant(stock=3, delta="5.00")  # price 25.00
        self.add_url = reverse("cart:add")

    def _add(self, qty=1, variant=None):
        return self.client.post(self.add_url, {"variant": (variant or self.variant).pk, "quantity": qty},
                                follow=True)

    def test_guest_can_add_and_see_totals(self):
        self._add(2)
        response = self.client.get(reverse("cart:detail"))
        summary = response.context["summary"]
        self.assertEqual(summary.item_count, 2)
        self.assertEqual(str(summary.total), "50.00")
        self.assertEqual(Cart.objects.get().user, None)

    def test_adding_same_variant_combines_lines(self):
        self._add(1)
        self._add(1)
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_cannot_exceed_stock(self):
        self._add(2)
        response = self._add(2)
        self.assertContains(response, "Only 3")
        self.assertEqual(CartItem.objects.get().quantity, 2)

    def test_sold_out_variant_blocked(self):
        sold_out = make_variant(color="Red", stock=0)
        response = self._add(1, sold_out)
        self.assertContains(response, "sold out")
        self.assertFalse(CartItem.objects.exists())

    def test_update_and_remove(self):
        self._add(1)
        item = CartItem.objects.get()
        self.client.post(reverse("cart:update", args=[item.pk]), {"quantity": 3})
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)
        self.client.post(reverse("cart:update", args=[item.pk]), {"quantity": 0})
        self.assertFalse(CartItem.objects.exists())

    def test_cannot_touch_another_carts_item(self):
        other = Cart.objects.create()
        foreign = CartItem.objects.create(cart=other, variant=self.variant, quantity=1)
        self._add(1)
        response = self.client.post(reverse("cart:remove", args=[foreign.pk]), follow=True)
        self.assertContains(response, "not in your cart")
        self.assertTrue(CartItem.objects.filter(pk=foreign.pk).exists())

    def test_line_flagged_when_stock_drops_below_quantity(self):
        """FR-X03: the cart re-checks current stock."""
        self._add(3)
        type(self.variant).objects.filter(pk=self.variant.pk).update(stock_qty=1)
        summary = self.client.get(reverse("cart:detail")).context["summary"]
        self.assertEqual(summary.issues[0].issue, "Only 1 left — reduce the quantity.")


class CartMergeTests(TestCase):
    """FR-X02: guest cart merges into the account cart on login."""

    def test_guest_cart_merged_on_login(self):
        user = make_user()
        v1 = make_variant(color="Black", stock=5)
        v2 = make_variant(product=v1.product, color="White", stock=2)
        # Customer already has 1 × v2 in their account cart.
        account_cart = Cart.objects.create(user=user)
        CartItem.objects.create(cart=account_cart, variant=v2, quantity=1)

        self.client.post(reverse("cart:add"), {"variant": v1.pk, "quantity": 2})
        self.client.post(reverse("cart:add"), {"variant": v2.pk, "quantity": 2})
        self.client.post(reverse("accounts:login"), {"email": user.email, "password": PASSWORD})

        items = {i.variant_id: i.quantity for i in CartItem.objects.filter(cart__user=user)}
        self.assertEqual(items, {v1.pk: 2, v2.pk: 2})  # v2 capped at stock (1 + 2 > 2)
        self.assertEqual(Cart.objects.filter(user__isnull=True).count(), 0)

    def test_navbar_count(self):
        make_variant(stock=5)
        v = make_variant(color="Grey", stock=5)
        self.client.post(reverse("cart:add"), {"variant": v.pk, "quantity": 2})
        response = self.client.get(reverse("core:home"))
        self.assertEqual(response.context["cart_count"], 2)
