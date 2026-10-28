import threading

from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.urls import reverse

from catalog.models import ProductVariant
from core.navigation import badges
from core.testing import make_staff, make_variant

from .models import StockMovement
from .services import InsufficientStock, InventoryService


class InventoryServiceTests(TestCase):
    def setUp(self):
        self.staff = make_staff()
        self.variant = make_variant(stock=0, safety=5)
        self.service = InventoryService(self.staff)

    def test_adjust_in_records_movement(self):
        movement = self.service.adjust(self.variant, 12, "Received from supplier")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 12)
        self.assertEqual((movement.type, movement.quantity, movement.balance_after), ("IN", 12, 12))
        self.assertEqual(movement.reference, "MANUAL")
        self.assertEqual(movement.user, self.staff)

    def test_cannot_go_below_zero(self):
        self.service.adjust(self.variant, 3, "Count")
        with self.assertRaises(InsufficientStock):
            self.service.adjust(self.variant, -4, "Damaged")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)
        self.assertEqual(StockMovement.objects.count(), 1)  # failed change leaves no row

    def test_deduct_and_restore_use_order_reference(self):
        self.service.adjust(self.variant, 10, "Count")
        system = InventoryService()  # no user = system
        out = system.deduct(self.variant, 4, "SF261028-ABC123")
        back = system.restore(self.variant, 4, "SF261028-ABC123")
        self.assertEqual((out.type, out.balance_after, out.user), ("OUT", 6, None))
        self.assertEqual((back.type, back.balance_after), ("IN", 10))

    def test_low_stock_query_and_badge(self):
        make_variant(color="White", stock=20, safety=5)
        self.assertEqual(list(InventoryService.low_stock_variants()), [self.variant])
        self.assertEqual(badges.value("low_stock"), 1)


class ConcurrentDeductionTests(TransactionTestCase):
    """FR-X06: two simultaneous orders for the last item — only one may win."""

    def test_last_item_sold_once(self):
        variant = make_variant(stock=1)
        results = []

        def buy():
            try:
                InventoryService().deduct(ProductVariant.objects.get(pk=variant.pk), 1, "RACE")
                results.append("ok")
            except InsufficientStock:
                results.append("rejected")
            finally:
                connection.close()

        threads = [threading.Thread(target=buy) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        variant.refresh_from_db()
        self.assertEqual(sorted(results), ["ok", "rejected"])
        self.assertEqual(variant.stock_qty, 0)


class InventoryViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())
        self.variant = make_variant(stock=2, safety=5)

    def test_adjust_view_requires_reason_and_warns_when_low(self):
        url = reverse("inventory_bo:adjust", args=[self.variant.pk])
        response = self.client.post(url, {"direction": "in", "quantity": 1, "reason": ""})
        self.assertEqual(response.status_code, 200)  # form error: reason required
        response = self.client.post(url, {"direction": "in", "quantity": 1, "reason": "Count"}, follow=True)
        self.assertContains(response, "below its safety level")
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.stock_qty, 3)

    def test_remove_more_than_available_is_a_form_error(self):
        url = reverse("inventory_bo:adjust", args=[self.variant.pk])
        response = self.client.post(url, {"direction": "out", "quantity": 5, "reason": "Damaged"})
        self.assertContains(response, "only 2 in stock")

    def test_lists_render_and_filter(self):
        InventoryService().adjust(self.variant, 1, "Count")
        self.assertContains(self.client.get(reverse("inventory_bo:stock_list"), {"status": "low"}),
                            self.variant.sku)
        self.assertContains(self.client.get(reverse("inventory_bo:movement_list"), {"type": "IN"}), "Count")
