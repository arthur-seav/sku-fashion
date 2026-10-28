from django.views.generic import TemplateView

from catalog.models import Category
from catalog.query import ProductCatalogQuery, ProductFilter
from promotions.pricing import PricingService


class HomeView(TemplateView):
    template_name = "core/home.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["new_arrivals"] = PricingService().decorate(
            list(ProductCatalogQuery(ProductFilter(sort="new")).queryset()[:8]))
        ctx["top_categories"] = Category.objects.filter(level=1)
        return ctx
