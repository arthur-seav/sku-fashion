from django.db.models import Count
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.html import format_html

from core.backoffice import CrudViewSet
from core.templatetags.ui import money

from .forms import CampaignForm, CouponForm
from .models import Campaign, Coupon, DiscountType


def _period(rule):
    fmt = lambda d: date_format(timezone.localtime(d), "j M Y H:i")  # noqa: E731
    return f"{fmt(rule.start_at)} → {fmt(rule.end_at)}"


def _value(rule):
    if rule.discount_type == DiscountType.PERCENT:
        return f"{rule.discount_value.normalize():f}%"
    return money(rule.discount_value)


def _state(rule):
    now = timezone.now()
    if not rule.is_active:
        label, tone = "Inactive", "outline"
    elif now < rule.start_at:
        label, tone = "Scheduled", "info"
    elif now > rule.end_at:
        label, tone = "Ended", "outline"
    else:
        label, tone = "Running", "success"
    return format_html('<span class="badge tone-{}">{}</span>', tone, label)


class CouponViewSet(CrudViewSet):
    model = Coupon
    form_class = CouponForm
    name = "coupon"
    namespace = "promotions_bo"
    section = "Promotions"
    description = "Codes customers enter at checkout. Each failure reason is reported to the customer."
    search_fields = ["code"]
    list_display = [
        ("Code", lambda c: format_html("<code>{}</code>", c.code)),
        ("Discount", _value),
        ("Min. spend", lambda c: money(c.min_spend)),
        ("Limits", lambda c: f"{c.usage_limit or '∞'} total · {c.per_user_limit or '∞'} per customer"),
        ("Period", _period),
        ("Status", _state),
    ]


class CampaignViewSet(CrudViewSet):
    model = Campaign
    form_class = CampaignForm
    name = "campaign"
    namespace = "promotions_bo"
    section = "Promotions"
    description = "Automatic discounts on selected categories or products for a period."
    search_fields = ["name"]
    list_display = [
        ("Campaign", "name"),
        ("Discount", _value),
        ("Covers", lambda c: f"{c.n_categories} categories · {c.n_products} products"),
        ("Period", _period),
        ("Status", _state),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(
            n_categories=Count("categories", distinct=True), n_products=Count("products", distinct=True))
