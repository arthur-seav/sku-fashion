from django.contrib import admin

from .models import Payment, Refund


class RefundInline(admin.TabularInline):
    model = Refund
    extra = 0


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ["order", "provider", "amount", "status", "paid_at"]
    list_filter = ["provider", "status"]
    inlines = [RefundInline]
