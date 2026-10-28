from django.contrib import admin

from .models import Campaign, CampaignCategory, CampaignProduct, Coupon


class CampaignCategoryInline(admin.TabularInline):
    model = CampaignCategory
    extra = 0


class CampaignProductInline(admin.TabularInline):
    model = CampaignProduct
    extra = 0


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ["name", "discount_type", "discount_value", "start_at", "end_at", "is_active"]
    inlines = [CampaignCategoryInline, CampaignProductInline]


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ["code", "discount_type", "discount_value", "min_spend", "start_at", "end_at", "is_active"]
    search_fields = ["code"]
