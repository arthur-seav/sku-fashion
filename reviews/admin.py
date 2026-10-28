from django.contrib import admin

from .models import Review


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["order_item", "rating", "status", "submitted_at", "moderated_by"]
    list_filter = ["status", "rating"]
    search_fields = ["order_item__product_name", "order_item__order__order_no", "order_item__order__user__email"]
    readonly_fields = ["order_item", "submitted_at", "moderated_by", "moderated_at"]
