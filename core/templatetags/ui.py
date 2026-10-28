"""Template helpers shared by storefront and back-office.

    {% load ui %}
    {% icon "package" %}            Lucide icon from the local sprite
    {{ amount|money }}             $1,234.50 in the store currency
    {{ order.status|tone }}        badge tone class for a status value
    {% backoffice_nav %}           the back-office sidebar
"""

from decimal import Decimal, InvalidOperation

from django import template
from django.conf import settings
from django.templatetags.static import static
from django.urls import NoReverseMatch, reverse
from django.utils.html import format_html

from core.navigation import BACKOFFICE_NAV, badges

register = template.Library()

CURRENCY_SYMBOLS = {"USD": "$", "KHR": "៛"}

STATUS_TONES = {
    # orders
    "PENDING_PAYMENT": "warning",
    "PAID": "info",
    "PREPARING": "neutral",
    "SHIPPED": "info",
    "COMPLETED": "success",
    "CANCELLED": "danger",
    # payments / shipments / generic
    "PENDING": "warning",
    "DELIVERED": "success",
    "IN": "success",
    "OUT": "danger",
    "CUSTOMER": "outline",
    "STAFF": "info",
    "ADMIN": "neutral",
    True: "success",
    False: "danger",
}


@register.simple_tag
def icon(name, css="icon"):
    href = f"{static('vendor/lucide/sprite.svg')}#i-{name}"
    return format_html('<svg class="{}" aria-hidden="true"><use href="{}"></use></svg>', css, href)


@register.filter
def money(value):
    if value in (None, ""):
        return ""
    try:
        amount = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    symbol = CURRENCY_SYMBOLS.get(settings.STORE_CURRENCY, settings.STORE_CURRENCY + " ")
    sign = "-" if amount < 0 else ""
    return f"{sign}{symbol}{abs(amount):,.2f}"


@register.filter
def tone(value):
    return f"tone-{STATUS_TONES.get(value, 'outline')}"


@register.filter
def percent(value):
    try:
        return f"{Decimal(value) * 100:.0f}%"
    except (InvalidOperation, TypeError, ValueError):
        return value


@register.inclusion_tag("backoffice/partials/sidebar.html", takes_context=True)
def backoffice_nav(context):
    request = context["request"]
    user = request.user
    match = request.resolver_match
    current = match.view_name if match else ""
    groups = []
    for group in BACKOFFICE_NAV:
        items = []
        for item in group.items:
            if item.admin_only and not user.is_admin_role:
                continue
            try:
                url = reverse(item.url_name)
            except NoReverseMatch:
                continue
            items.append({
                "label": item.label,
                "url": url,
                "icon": item.icon,
                "active": any(current.startswith(prefix) for prefix in item.match),
                "badge": badges.value(item.badge) if item.badge else 0,
                "badge_key": item.badge,
            })
        if items:
            groups.append({"label": group.label, "items": items})
    return {"groups": groups}
