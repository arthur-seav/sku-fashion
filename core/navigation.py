"""Back-office sidebar configuration (after AdminCN's configs/navConfig.tsx).

Each app contributes its menu entries here by URL name; apps that need a
live counter on their entry (e.g. low-stock variants) register a badge
provider from their AppConfig.ready(), so this module never imports app
models directly.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str
    match: tuple = ()          # view-name prefixes that mark this entry active
    admin_only: bool = False
    badge: str = ""            # key of a registered badge provider


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: list = field(default_factory=list)


BACKOFFICE_NAV = [
    NavGroup("Overview", [
        NavItem("Dashboard", "reporting:dashboard", "layout-dashboard", ("reporting:dashboard",)),
        NavItem("Sales report", "reporting:sales", "chart-column", ("reporting:sales",)),
        NavItem("Best sellers", "reporting:best_sellers", "trending-up", ("reporting:best_sellers",)),
        NavItem("Stock report", "reporting:stock", "package-x", ("reporting:stock",)),
    ]),
    NavGroup("Sales", [
        NavItem("Orders", "orders_bo:order_list", "shopping-bag", ("orders_bo:",), badge="orders_awaiting"),
        NavItem("Shipping methods", "shipping_bo:method_list", "truck", ("shipping_bo:method_",)),
        NavItem("Shipping rates", "shipping_bo:rate_list", "map-pin", ("shipping_bo:rate_",)),
    ]),
    NavGroup("Catalog", [
        NavItem("Products", "catalog_bo:product_list", "shirt", ("catalog_bo:product_", "catalog_bo:variant_")),
        NavItem("Reviews", "reviews_bo:review_list", "message-square-text", ("reviews_bo:",),
                badge="reviews_pending"),
        NavItem("Categories", "catalog_bo:category_list", "list-tree", ("catalog_bo:category_",)),
        NavItem("Brands", "catalog_bo:brand_list", "award", ("catalog_bo:brand_",)),
        NavItem("Materials", "catalog_bo:material_list", "layers", ("catalog_bo:material_",)),
        NavItem("Sizes", "catalog_bo:size_list", "ruler", ("catalog_bo:size_", )),
        NavItem("Colors", "catalog_bo:color_list", "palette", ("catalog_bo:color_",)),
        NavItem("Size charts", "catalog_bo:sizechart_list", "table", ("catalog_bo:sizechart_",)),
    ]),
    NavGroup("Inventory", [
        NavItem("Stock levels", "inventory_bo:stock_list", "boxes", ("inventory_bo:stock_", "inventory_bo:adjust"),
                badge="low_stock"),
        NavItem("Stock movements", "inventory_bo:movement_list", "history", ("inventory_bo:movement_",)),
    ]),
    NavGroup("Promotions", [
        NavItem("Coupons", "promotions_bo:coupon_list", "ticket-percent", ("promotions_bo:coupon_",)),
        NavItem("Campaigns", "promotions_bo:campaign_list", "megaphone", ("promotions_bo:campaign_",)),
    ]),
    NavGroup("Administration", [
        NavItem("Back-office accounts", "accounts_bo:account_list", "user-cog", ("accounts_bo:",),
                admin_only=True),
    ]),
]


class BadgeRegistry:
    """Maps a badge key to a zero-argument callable returning a number."""

    def __init__(self):
        self._providers = {}

    def register(self, key, provider):
        self._providers[key] = provider

    def value(self, key):
        provider = self._providers.get(key)
        return provider() if provider else 0


badges = BadgeRegistry()
