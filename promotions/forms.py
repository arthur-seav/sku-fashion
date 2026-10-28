from django import forms

from catalog.models import Category, Product
from core.forms import BootstrapFormMixin, DateTimeInput

from .models import Campaign, Coupon

DATE_FIELDS = {"start_at": DateTimeInput(), "end_at": DateTimeInput()}


class CouponForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Coupon
        fields = ["code", "discount_type", "discount_value", "min_spend", "usage_limit", "per_user_limit",
                  "start_at", "end_at", "is_active"]
        widgets = DATE_FIELDS


class CampaignForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Campaign
        fields = ["name", "discount_type", "discount_value", "start_at", "end_at", "categories", "products",
                  "is_active"]
        widgets = {
            **DATE_FIELDS,
            "categories": forms.CheckboxSelectMultiple,
            "products": forms.SelectMultiple(attrs={"size": 10}),
        }
        help_texts = {
            "categories": "Covers every product in the category and its sub-categories.",
            "products": "Hold Ctrl to select several.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["categories"].queryset = Category.objects.select_related("parent__parent")
        self.fields["products"].queryset = Product.objects.filter(is_active=True).order_by("name")

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("categories") and not cleaned.get("products"):
            raise forms.ValidationError("Select at least one category or product.")
        return cleaned
