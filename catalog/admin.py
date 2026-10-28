from django.contrib import admin

from .models import (Brand, Category, Color, Material, Product, ProductImage, ProductMaterial,
                     ProductVariant, Size, SizeChart)

admin.site.register([Brand, Material, Size, Color, SizeChart])


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["__str__", "level", "slug"]


class VariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0
    readonly_fields = ["stock_qty"]


class ImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class MaterialInline(admin.TabularInline):
    model = ProductMaterial
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "brand", "base_price", "is_active"]
    list_filter = ["is_active", "brand"]
    search_fields = ["name", "variants__sku"]
    inlines = [MaterialInline, ImageInline, VariantInline]
