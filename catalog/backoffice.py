"""Back-office screens for the catalog (UC-11, UC-12, UC-13)."""

from django.contrib import messages
from django.db.models import Count, ProtectedError, Q, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View
from django.views.generic import DetailView, FormView, UpdateView

from core.backoffice import CrudCreateView, CrudUpdateView, CrudViewSet
from core.permissions import StaffRequiredMixin
from core.templatetags.ui import money

from .forms import (BrandForm, CategoryForm, ColorForm, MaterialForm, ProductForm,
                    ProductImageUploadForm, SizeChartForm, SizeForm, VariantForm, VariantGenerateForm)
from .models import Brand, Category, Color, Material, Product, ProductImage, ProductVariant, Size, SizeChart
from .services import VariantGenerator

NAMESPACE = "catalog_bo"


class CatalogViewSet(CrudViewSet):
    namespace = NAMESPACE
    section = "Catalog"


class CategoryViewSet(CatalogViewSet):
    model = Category
    form_class = CategoryForm
    name = "category"
    description = "A tree of up to three levels, e.g. Women › Tops › T-Shirts."
    list_display = [("Category", lambda c: str(c)), ("Level", "level"), ("Slug", "slug"),
                    ("Products", lambda c: c.product_count)]
    search_fields = ["name"]
    select_related = ("parent__parent",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(product_count=Count("products"))\
            .order_by("parent__parent__name", "parent__name", "name")


class BrandViewSet(CatalogViewSet):
    model = Brand
    form_class = BrandForm
    name = "brand"
    list_display = [("Brand", "name"), ("Slug", "slug"), ("Products", lambda b: b.product_count)]
    search_fields = ["name"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(product_count=Count("products"))


class MaterialViewSet(CatalogViewSet):
    model = Material
    form_class = MaterialForm
    name = "material"
    list_display = [("Material", "name")]
    search_fields = ["name"]


class SizeViewSet(CatalogViewSet):
    model = Size
    form_class = SizeForm
    name = "size"
    description = "Sort order controls how sizes are listed (XS before S before M …)."
    list_display = [("Size", "name"), ("Sort order", "sort_order")]


class ColorViewSet(CatalogViewSet):
    model = Color
    form_class = ColorForm
    name = "color"
    list_display = [
        ("Color", lambda c: format_html('<span class="color-swatch me-2" style="background:{}"></span>{}',
                                        c.hex_code, c.name)),
        ("Hex", "hex_code"), ("Sort order", "sort_order"),
    ]
    search_fields = ["name"]


class SizeChartViewSet(CatalogViewSet):
    model = SizeChart
    form_class = SizeChartForm
    name = "sizechart"
    title = "Size chart"
    title_plural = "Size charts"
    description = "A chart applies to its category and every sub-category without its own chart."
    list_display = [("Chart", "name"), ("Category", lambda s: str(s.category))]
    select_related = ("category__parent__parent",)


# --------------------------------------------------------------------------
# Products
# --------------------------------------------------------------------------
def product_thumb(product):
    image = product.primary_image
    if image:
        return format_html('<img class="thumb" src="{}" alt="">', image.image.url)
    return mark_safe('<span class="thumb d-inline-block"></span>')


class ProductCreateView(CrudCreateView):
    def get_success_url(self):
        return reverse("catalog_bo:product_detail", args=[self.object.pk])


class ProductUpdateView(CrudUpdateView):
    def get_success_url(self):
        return reverse("catalog_bo:product_detail", args=[self.object.pk])


class ProductViewSet(CatalogViewSet):
    model = Product
    form_class = ProductForm
    name = "product"
    detail_url_name = "catalog_bo:product_detail"
    create_view_class = ProductCreateView
    update_view_class = ProductUpdateView
    list_display = [
        ("Product", lambda p: format_html('<span class="d-inline-flex align-items-center gap-2">{}{}</span>',
                                          product_thumb(p), p.name)),
        ("Category", lambda p: p.category.name),
        ("Brand", "brand.name"),
        ("Base price", lambda p: money(p.base_price)),
        ("Variants", lambda p: p.variant_count),
        ("Stock", lambda p: p.total_stock or 0),
        ("Active", "is_active"),
    ]
    search_fields = ["name", "brand__name"]
    select_related = ("category", "brand")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        q = request.GET.get("q", "").strip()
        if q:  # also match SKU codes, via a sub-query so the counts below stay correct
            sku_match = Product.objects.filter(variants__sku__icontains=q).values("pk")
            qs = (Product.objects.select_related(*self.select_related)
                  .filter(Q(name__icontains=q) | Q(brand__name__icontains=q) | Q(pk__in=sku_match)))
        qs = qs.prefetch_related("images").annotate(
            variant_count=Count("variants", distinct=True),
            total_stock=Sum("variants__stock_qty"),
        )
        return qs.order_by("-created_at")


class ProductDetailView(StaffRequiredMixin, DetailView):
    template_name = "catalog/backoffice/product_detail.html"
    queryset = Product.objects.select_related("category__parent__parent", "brand").prefetch_related(
        "materials", "images__color")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["variants"] = self.object.variants.select_related("color", "size")
        ctx["upload_form"] = ProductImageUploadForm()
        return ctx


class ProductImageUploadView(StaffRequiredMixin, View):
    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        form = ProductImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            created = form.save(product)
            messages.success(request, f"{len(created)} image(s) uploaded.")
        else:
            for errors in form.errors.values():
                for error in errors:
                    messages.error(request, error)
        return redirect("catalog_bo:product_detail", pk=pk)


class ProductImageActionView(StaffRequiredMixin, View):
    def post(self, request, pk, action):
        image = get_object_or_404(ProductImage, pk=pk)
        product_pk = image.product_id
        if action == "primary":
            image.make_primary()
            messages.success(request, "Primary image updated.")
        elif action == "delete":
            was_primary = image.is_primary
            image.image.delete(save=False)
            image.delete()
            if was_primary:
                replacement = ProductImage.objects.filter(product_id=product_pk).first()
                if replacement:
                    replacement.make_primary()
            messages.success(request, "Image deleted.")
        return redirect("catalog_bo:product_detail", pk=product_pk)


# --------------------------------------------------------------------------
# Variants (UC-13)
# --------------------------------------------------------------------------
class VariantGenerateView(StaffRequiredMixin, FormView):
    """Step 1–4: pick sizes, colors and price; step 5–6: preview, then confirm."""

    template_name = "catalog/backoffice/variant_generate.html"
    form_class = VariantGenerateForm

    def dispatch(self, request, *args, **kwargs):
        self.product = get_object_or_404(Product, pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["product"] = self.product
        return ctx

    def form_valid(self, form):
        generator = VariantGenerator(self.product)
        sizes, colors = list(form.cleaned_data["sizes"]), list(form.cleaned_data["colors"])
        if self.request.POST.get("action") != "confirm":
            combos = generator.preview(sizes, colors)
            return self.render_to_response(self.get_context_data(
                form=form, combos=combos, new_count=sum(c.is_new for c in combos)))
        created, skipped = generator.generate(
            sizes, colors, form.cleaned_data["price_delta"], form.cleaned_data["safety_level"])
        messages.success(self.request, f"{len(created)} variant(s) created with zero stock; "
                                       f"{skipped} existing combination(s) kept.")
        return redirect("catalog_bo:product_detail", pk=self.product.pk)


class VariantUpdateView(StaffRequiredMixin, UpdateView):
    model = ProductVariant
    form_class = VariantForm
    template_name = "catalog/backoffice/variant_form.html"

    def get_queryset(self):
        return ProductVariant.objects.select_related("product", "color", "size")

    def form_valid(self, form):
        messages.success(self.request, f"Variant {self.object.sku} updated.")
        return super().form_valid(form)

    def get_success_url(self):
        return reverse("catalog_bo:product_detail", args=[self.object.product_id])


class VariantDeleteView(StaffRequiredMixin, View):
    def post(self, request, pk):
        variant = get_object_or_404(ProductVariant, pk=pk)
        product_pk = variant.product_id
        try:
            variant.delete()
            messages.success(request, f"Variant {variant.sku} deleted.")
        except ProtectedError:
            messages.error(request, f"{variant.sku} has stock or order history and cannot be deleted. "
                                    f"Mark it inactive instead.")
        return redirect("catalog_bo:product_detail", pk=product_pk)
