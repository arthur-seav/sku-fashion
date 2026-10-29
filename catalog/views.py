"""Storefront catalog views (UC-03 Browse & Search, UC-04 View Product Details)."""

from django.shortcuts import get_object_or_404
from django.views.generic import DetailView, ListView

from promotions.pricing import PricingService
from reviews.services import ProductReviews

from .models import Product
from .query import ProductCatalogQuery, ProductFilter


class ProductListView(ListView):
    template_name = "catalog/product_list.html"
    context_object_name = "products"
    paginate_by = 12

    def get_queryset(self):
        self.filter = ProductFilter.from_params(self.request.GET)
        return ProductCatalogQuery(self.filter).queryset()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["f"] = self.filter
        ctx.update(ProductCatalogQuery.facets())
        PricingService().decorate(ctx["products"])
        return ctx


class ProductDetailView(DetailView):
    template_name = "catalog/product_detail.html"
    context_object_name = "product"

    def get_object(self, queryset=None):
        return get_object_or_404(
            Product.objects.select_related("brand", "category__parent__parent")
            .prefetch_related("images__color", "materials"),
            slug=self.kwargs["slug"], is_active=True,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        product = self.object
        variants = list(product.variants.filter(is_active=True).select_related("color", "size"))
        for v in variants:
            v.product = product  # avoid one query per variant for v.price
        # Group sizes under each color for the picker.
        by_color = {}
        for v in variants:
            by_color.setdefault(v.color, []).append(v)
        pricing = PricingService()
        for v in variants:
            quote = pricing.quote(v)
            v.unit_price, v.campaign = quote.unit, quote.campaign
        ctx["variants"] = variants
        product.min_price = min((v.price for v in variants), default=product.base_price)
        pricing.decorate([product])
        ctx["campaign"] = product.campaign
        ctx["variants_by_color"] = by_color.items()
        ctx["size_chart"] = product.size_chart()
        ctx["breadcrumbs"] = [*product.category.ancestors(), product.category]
        reviews = ProductReviews(product)
        ctx["review_summary"] = reviews.summary()
        ctx["reviews"] = reviews.published()
        return ctx
