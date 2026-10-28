from django.contrib import admin

from .models import Order, OrderItem, OrderStatusHistory


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ["variant", "product_name", "variant_spec", "original_price", "unit_price", "quantity",
                       "line_total", "campaign"]


class HistoryInline(admin.TabularInline):
    model = OrderStatusHistory
    extra = 0
    readonly_fields = ["from_status", "to_status", "user", "note", "created_at"]


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ["order_no", "user", "status", "grand_total", "placed_at"]
    list_filter = ["status"]
    search_fields = ["order_no", "user__email"]
    inlines = [OrderItemInline, HistoryInline]
