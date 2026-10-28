"""Storefront catalog queries: browse, search and filter (FR-G02, NFR-01).

Multi-valued filters (size, color, material) use EXISTS sub-queries rather
than joins, so they never duplicate rows or distort the price annotation,
and the listing runs a fixed number of queries regardless of page size.
"""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from django.db.models import Exists, F, Min, OuterRef, Q

from .models import Brand, Category, Color, Material, Product, ProductVariant, Size


def _ids(values):
    out = []
    for v in values:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _decimal(value):
    try:
        return Decimal(value) if value not in (None, "") else None
    except InvalidOperation:
        return None


@dataclass
class ProductFilter:
    q: str = ""
    category: Category | None = None
    sizes: list = field(default_factory=list)
    colors: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    brands: list = field(default_factory=list)
    min_price: Decimal | None = None
    max_price: Decimal | None = None
    sort: str = "new"

    SORTS = {
        "new": ("Newest", ["-created_at"]),
        "price_asc": ("Price: low to high", ["min_price", "name"]),
        "price_desc": ("Price: high to low", ["-min_price", "name"]),
        "name": ("Name", ["name"]),
    }

    @classmethod
    def from_params(cls, params):
        category = None
        if params.get("category"):
            category = Category.objects.filter(slug=params["category"]).first()
        sort = params.get("sort", "new")
        return cls(
            q=params.get("q", "").strip(),
            category=category,
            sizes=_ids(params.getlist("size")),
            colors=_ids(params.getlist("color")),
            materials=_ids(params.getlist("material")),
            brands=_ids(params.getlist("brand")),
            min_price=_decimal(params.get("min_price")),
            max_price=_decimal(params.get("max_price")),
            sort=sort if sort in cls.SORTS else "new",
        )

    @property
    def is_filtered(self):
        return any([self.q, self.category, self.sizes, self.colors, self.materials, self.brands,
                    self.min_price is not None, self.max_price is not None])


class ProductCatalogQuery:
    """Builds the storefront product queryset for a `ProductFilter`."""

    def __init__(self, product_filter):
        self.f = product_filter

    @staticmethod
    def _active_variants():
        return ProductVariant.objects.filter(product=OuterRef("pk"), is_active=True)

    def queryset(self):
        f = self.f
        qs = (Product.objects.filter(is_active=True)
              .filter(Exists(self._active_variants()))
              .select_related("brand", "category")
              .prefetch_related("images")
              .annotate(min_price=Min(F("base_price") + F("variants__price_delta"),
                                      filter=Q(variants__is_active=True))))
        if f.q:
            qs = qs.filter(Q(name__icontains=f.q) | Q(description__icontains=f.q)
                           | Q(brand__name__icontains=f.q) | Q(category__name__icontains=f.q))
        if f.category:
            qs = qs.filter(category_id__in=f.category.descendant_ids())
        if f.brands:
            qs = qs.filter(brand_id__in=f.brands)
        if f.sizes:
            qs = qs.filter(Exists(self._active_variants().filter(size_id__in=f.sizes)))
        if f.colors:
            qs = qs.filter(Exists(self._active_variants().filter(color_id__in=f.colors)))
        if f.materials:
            qs = qs.filter(Exists(Product.materials.through.objects.filter(
                product=OuterRef("pk"), material_id__in=f.materials)))
        if f.min_price is not None:
            qs = qs.filter(min_price__gte=f.min_price)
        if f.max_price is not None:
            qs = qs.filter(min_price__lte=f.max_price)
        return qs.order_by(*ProductFilter.SORTS[f.sort][1])

    @staticmethod
    def facets():
        """Options for the filter sidebar."""
        return {
            "categories": Category.objects.filter(level=1).prefetch_related("children__children"),
            "brands": Brand.objects.all(),
            "sizes": Size.objects.all(),
            "colors": Color.objects.all(),
            "materials": Material.objects.all(),
            "sorts": [(key, label) for key, (label, _) in ProductFilter.SORTS.items()],
        }
