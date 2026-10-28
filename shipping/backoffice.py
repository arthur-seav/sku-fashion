from django import forms
from django.db.models import Count
from django.utils.html import format_html

from core.backoffice import CrudViewSet
from core.forms import BootstrapFormMixin
from core.templatetags.ui import money

from .models import ShippingMethod, ShippingRate


class ShippingMethodForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ShippingMethod
        fields = ["name", "base_fee", "free_threshold", "is_active"]


class ShippingRateForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ShippingRate
        fields = ["method", "province", "fee"]


class ShippingMethodViewSet(CrudViewSet):
    model = ShippingMethod
    form_class = ShippingMethodForm
    name = "method"
    namespace = "shipping_bo"
    section = "Shipping"
    title = "Shipping method"
    description = "Store pick-up is a method with a base fee of 0."
    list_display = [
        ("Method", "name"),
        ("Base fee", lambda m: money(m.base_fee)),
        ("Free from", lambda m: money(m.free_threshold) if m.free_threshold is not None else None),
        ("Province rates", lambda m: m.rate_count),
        ("Active", "is_active"),
    ]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(rate_count=Count("rates"))


class ShippingRateViewSet(CrudViewSet):
    model = ShippingRate
    form_class = ShippingRateForm
    name = "rate"
    namespace = "shipping_bo"
    section = "Shipping"
    title = "Shipping rate"
    description = "A province-specific fee overrides the method's base fee."
    search_fields = ["province", "method__name"]
    select_related = ("method",)
    list_display = [
        ("Rate", lambda r: format_html("{} → {}", r.method.name, r.province)),
        ("Fee", lambda r: money(r.fee)),
    ]
