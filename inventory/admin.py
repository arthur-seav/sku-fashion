from django.contrib import admin

from .models import StockMovement


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ["created_at", "variant", "type", "quantity", "balance_after", "reason", "reference", "user"]
    list_filter = ["type"]
    search_fields = ["variant__sku", "reference"]

    def has_change_permission(self, request, obj=None):
        return False  # the movement log is append-only
