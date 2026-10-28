"""Prices after campaign discounts (FR-S09).

`PricingService` loads the running campaigns once (two small queries plus the
category tree) and then prices any number of variants in memory, so product
listings stay free of N+1 queries (NFR-01).
"""

from dataclasses import dataclass
from decimal import Decimal

from django.utils import timezone

from catalog.models import Category

from .models import Campaign, CampaignCategory, CampaignProduct


@dataclass
class PriceQuote:
    original: Decimal          # variant price before any campaign
    unit: Decimal              # price actually charged
    campaign: object = None    # Campaign applied, if any

    @property
    def discount(self):
        return self.original - self.unit


def list_price(variant):
    """A pricer that ignores promotions (used where campaigns must not apply)."""
    return PriceQuote(original=variant.price, unit=variant.price)


class PricingService:
    def __init__(self, now=None):
        self.now = now or timezone.now()
        self._loaded = False

    def _load(self):
        if self._loaded:
            return
        campaigns = list(Campaign.objects.filter(is_active=True, start_at__lte=self.now, end_at__gte=self.now))
        ids = [c.pk for c in campaigns]
        self._by_product, self._by_category = {}, {}
        for cid, pid in CampaignProduct.objects.filter(campaign_id__in=ids).values_list("campaign_id", "product_id"):
            self._by_product.setdefault(pid, set()).add(cid)
        for cid, cat in CampaignCategory.objects.filter(campaign_id__in=ids).values_list("campaign_id", "category_id"):
            self._by_category.setdefault(cat, set()).add(cid)
        self._campaigns = {c.pk: c for c in campaigns}
        self._parents = dict(Category.objects.values_list("pk", "parent_id")) if self._by_category else {}
        self._loaded = True

    def campaigns_for(self, product):
        """Running campaigns that cover the product directly or via its category
        or any ancestor category."""
        self._load()
        ids = set(self._by_product.get(product.pk, ()))
        category_id = product.category_id
        while category_id is not None:
            ids |= self._by_category.get(category_id, set())
            category_id = self._parents.get(category_id)
        return [self._campaigns[i] for i in ids]

    def best_discount(self, product, amount):
        best, chosen = Decimal("0.00"), None
        for campaign in self.campaigns_for(product):
            discount = campaign.discount_on(amount)
            if discount > best:
                best, chosen = discount, campaign
        return best, chosen

    def quote(self, variant):
        original = variant.price
        discount, campaign = self.best_discount(variant.product, original)
        return PriceQuote(original=original, unit=original - discount, campaign=campaign)

    def decorate(self, products):
        """Set `sale_price` / `campaign` on listing products (uses `min_price`)."""
        for product in products:
            base = getattr(product, "min_price", None) or product.base_price
            discount, campaign = self.best_discount(product, base)
            product.campaign = campaign
            product.sale_price = base - discount if campaign else None
        return products
