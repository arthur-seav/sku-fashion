"""Dashboard KPIs and reports (UC-19, FR-S10, FR-S11, DFD 6.9).

Revenue is the grand total of orders placed in the period, excluding
cancelled orders (bank transfers still awaiting payment are included and
shown separately as "awaiting payment").
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth
from django.utils import timezone

from core.money import ZERO
from inventory.services import InventoryService
from orders.backoffice import awaiting_action_q
from orders.models import Order, OrderItem, OrderStatus


def day_bounds(start_date, end_date):
    """[start 00:00, end+1 00:00) in the store's local time zone."""
    tz = timezone.get_current_timezone()
    return (timezone.make_aware(datetime.combine(start_date, time.min), tz),
            timezone.make_aware(datetime.combine(end_date + timedelta(days=1), time.min), tz))


@dataclass
class Period:
    start: object  # date
    end: object    # date

    @classmethod
    def last_days(cls, days, today=None):
        today = today or timezone.localdate()
        return cls(today - timedelta(days=days - 1), today)

    @property
    def bounds(self):
        return day_bounds(self.start, self.end)


class ReportService:
    def __init__(self, now=None):
        self.now = now or timezone.now()
        self.today = timezone.localdate(self.now)

    def _orders(self, period, include_cancelled=False):
        start, end = period.bounds
        qs = Order.objects.filter(placed_at__gte=start, placed_at__lt=end)
        return qs if include_cancelled else qs.exclude(status=OrderStatus.CANCELLED)

    # ---- dashboard (FR-S10) ------------------------------------------------------
    def dashboard(self):
        today = Period(self.today, self.today)
        today_orders = self._orders(today)
        week = Period.last_days(7, self.today)
        awaiting = Order.objects.filter(awaiting_action_q()).distinct()
        low_stock = InventoryService.low_stock_variants().order_by("stock_qty")
        return {
            "today_revenue": today_orders.aggregate(v=Sum("grand_total"))["v"] or ZERO,
            "today_orders": today_orders.count(),
            "today_cancelled": self._orders(today, True).filter(status=OrderStatus.CANCELLED).count(),
            "awaiting_total": awaiting.count(),
            "awaiting": {
                "to_reconcile": awaiting.filter(status=OrderStatus.PENDING_PAYMENT).count(),
                "to_prepare": Order.objects.filter(status=OrderStatus.PAID).count(),
                "to_ship": Order.objects.filter(status=OrderStatus.PREPARING).count(),
            },
            "awaiting_orders": awaiting.select_related("user").prefetch_related("payments").order_by("placed_at")[:6],
            "low_stock_count": low_stock.count(),
            "low_stock": low_stock[:8],
            "week": self.sales_by(week, "day"),
            "week_revenue": self._orders(week).aggregate(v=Sum("grand_total"))["v"] or ZERO,
            "best_sellers": self.best_sellers(Period.last_days(30, self.today), limit=5),
        }

    # ---- sales report (FR-S11) ---------------------------------------------------------
    def sales_by(self, period, group="day"):
        trunc = TruncMonth if group == "month" else TruncDay
        tz = timezone.get_current_timezone()
        rows = {
            r["bucket"].date() if hasattr(r["bucket"], "date") else r["bucket"]: r
            for r in self._orders(period).annotate(bucket=trunc("placed_at", tzinfo=tz)).values("bucket").annotate(
                orders=Count("id"), gross=Sum("subtotal"), discounts=Sum("discount_total"),
                tax=Sum("tax_total"), shipping=Sum("shipping_fee"), revenue=Sum("grand_total"))
        }
        items = {
            (r["bucket"].date() if hasattr(r["bucket"], "date") else r["bucket"]): r["qty"]
            for r in OrderItem.objects.filter(order__in=self._orders(period))
            .annotate(bucket=trunc("order__placed_at", tzinfo=tz)).values("bucket").annotate(qty=Sum("quantity"))
        }
        # One row per day/month in the period, zeros included, so charts have no gaps.
        buckets, cursor = [], period.start if group == "day" else period.start.replace(day=1)
        while cursor <= period.end:
            buckets.append(cursor)
            if group == "day":
                cursor += timedelta(days=1)
            else:
                cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
        out = []
        for b in buckets:
            r = rows.get(b, {})
            out.append({
                "bucket": b, "orders": r.get("orders", 0), "items": items.get(b, 0),
                "gross": r.get("gross") or ZERO, "discounts": r.get("discounts") or ZERO,
                "tax": r.get("tax") or ZERO, "shipping": r.get("shipping") or ZERO,
                "revenue": r.get("revenue") or ZERO,
            })
        peak = max((row["revenue"] for row in out), default=ZERO) or Decimal("1")
        for row in out:
            row["pct"] = int(row["revenue"] / peak * 100)
        return out

    @staticmethod
    def totals(rows):
        keys = ["orders", "items", "gross", "discounts", "tax", "shipping", "revenue"]
        return {k: sum((r[k] for r in rows), 0) for k in keys}

    # ---- best sellers (FR-S11) ---------------------------------------------------------
    def best_sellers(self, period, limit=20):
        return list(
            OrderItem.objects.filter(order__in=self._orders(period))
            .values(product_id=F("variant__product_id"), name=F("variant__product__name"))
            .annotate(qty=Sum("quantity"), revenue=Sum("line_total"), orders=Count("order", distinct=True))
            .order_by("-qty", "-revenue")[:limit]
        )

    # ---- stock report (FR-S11) -----------------------------------------------------------
    @staticmethod
    def stock_report(kind="alert"):
        qs = InventoryService.low_stock_variants()
        if kind == "sold_out":
            qs = qs.filter(stock_qty=0)
        elif kind == "low":
            qs = qs.filter(stock_qty__gt=0)
        return qs.annotate(shortfall=F("safety_level") - F("stock_qty")).order_by("stock_qty", "product__name")

    @staticmethod
    def stock_summary():
        qs = InventoryService.low_stock_variants()
        return qs.aggregate(sold_out=Count("id", filter=Q(stock_qty=0)), low=Count("id", filter=Q(stock_qty__gt=0)))
