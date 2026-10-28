from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.testing import make_product, make_staff, make_user, make_variant
from orders.models import Order, OrderItem, OrderStatus
from payments.models import Payment
from shipping.models import ShippingMethod

from .services import Period, ReportService


class ReportFixture(TestCase):
    def setUp(self):
        self.customer = make_user()
        self.method = ShippingMethod.objects.create(name="Std", base_fee=Decimal("2"))
        self.tee = make_variant(make_product("Tee", "10.00"), stock=50, safety=5)
        self.jeans = make_variant(make_product("Jeans", "40.00"), stock=2, safety=5)
        self.today = timezone.localdate()

    def order(self, total, status=OrderStatus.PREPARING, days_ago=0, items=(), provider="COD"):
        order = Order.objects.create(
            order_no=Order.generate_order_no(), user=self.customer, status=status,
            subtotal=total, discount_total=0, tax_total=0, shipping_fee=0, grand_total=Decimal(total),
            ship_recipient="x", ship_phone="x", ship_province="Kep", ship_district="x", ship_line_1="x",
            shipping_method=self.method)
        Order.objects.filter(pk=order.pk).update(placed_at=timezone.now() - timedelta(days=days_ago))
        for variant, qty in items:
            OrderItem.objects.create(order=order, variant=variant, product_name=variant.product.name,
                                     variant_spec=variant.spec, original_price=variant.price,
                                     unit_price=variant.price, quantity=qty, line_total=variant.price * qty)
        Payment.objects.create(order=order, provider=provider, amount=total)
        return order


class ReportServiceTests(ReportFixture):
    def test_dashboard_kpis(self):
        self.order("30.00", items=[(self.tee, 3)])
        self.order("40.00", status=OrderStatus.PAID, items=[(self.jeans, 1)])
        self.order("99.00", status=OrderStatus.CANCELLED)
        self.order("50.00", days_ago=3)
        d = ReportService().dashboard()
        self.assertEqual(d["today_revenue"], Decimal("70.00"))   # cancelled excluded
        self.assertEqual(d["today_orders"], 2)
        self.assertEqual(d["today_cancelled"], 1)
        self.assertEqual(d["awaiting"]["to_prepare"], 1)
        self.assertEqual(d["awaiting"]["to_ship"], 2)
        self.assertEqual(d["week_revenue"], Decimal("120.00"))
        self.assertEqual(list(d["low_stock"]), [self.jeans])   # 2 < safety 5

    def test_sales_by_day_has_a_row_for_every_day(self):
        self.order("30.00", items=[(self.tee, 3)])
        self.order("20.00", days_ago=2, items=[(self.tee, 2)])
        rows = ReportService().sales_by(Period.last_days(7), "day")
        self.assertEqual(len(rows), 7)
        totals = ReportService.totals(rows)
        self.assertEqual((totals["orders"], totals["items"], totals["revenue"]), (2, 5, Decimal("50.00")))
        self.assertEqual(rows[-1]["pct"], 100)  # today is the peak

    def test_sales_by_month(self):
        self.order("30.00")
        rows = ReportService().sales_by(Period(self.today - timedelta(days=60), self.today), "month")
        self.assertTrue(all(r["bucket"].day == 1 for r in rows))
        self.assertEqual(ReportService.totals(rows)["revenue"], Decimal("30.00"))

    def test_best_sellers_ranked_by_units(self):
        self.order("40.00", items=[(self.jeans, 1)])
        self.order("50.00", items=[(self.tee, 5)])
        self.order("10.00", status=OrderStatus.CANCELLED, items=[(self.jeans, 9)])  # ignored
        ranking = ReportService().best_sellers(Period.last_days(30))
        self.assertEqual([(r["name"], r["qty"]) for r in ranking], [("Tee", 5), ("Jeans", 1)])

    def test_stock_report_kinds(self):
        sold_out = make_variant(self.tee.product, color="Red", stock=0)
        self.assertEqual(set(ReportService.stock_report("alert")), {self.jeans, sold_out})
        self.assertEqual(list(ReportService.stock_report("sold_out")), [sold_out])
        self.assertEqual(list(ReportService.stock_report("low")), [self.jeans])


class ReportViewTests(ReportFixture):
    def setUp(self):
        super().setUp()
        self.client.force_login(make_staff())
        self.order("30.00", items=[(self.tee, 3)])

    def test_pages_render(self):
        for name in ["dashboard", "sales", "best_sellers", "stock"]:
            self.assertEqual(self.client.get(reverse(f"reporting:{name}")).status_code, 200, name)
        self.assertContains(self.client.get(reverse("reporting:dashboard")), "$30.00")

    def test_csv_export(self):
        response = self.client.get(reverse("reporting:sales"), {"format": "csv"})
        self.assertEqual(response["Content-Type"], "text/csv")
        self.assertIn(b"period,orders,items", response.content)

    def test_invalid_period_falls_back(self):
        response = self.client.get(reverse("reporting:sales"), {"start": "2026-10-10", "end": "2026-10-01"})
        self.assertContains(response, "on or after the start date")

    def test_customer_forbidden(self):
        self.client.force_login(make_user("c2@example.com"))
        self.assertEqual(self.client.get(reverse("reporting:sales")).status_code, 403)
