from decimal import Decimal

from django import forms

from core.forms import BootstrapFormMixin
from core.validators import validate_image_size

from .models import (Brand, Category, Color, Material, Product, ProductImage, ProductVariant,
                     Size, SizeChart)


class CategoryForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["parent", "name", "slug"]
        help_texts = {"slug": "Leave blank to generate from the name."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        parents = Category.objects.filter(level__lt=Category.MAX_LEVEL)
        if self.instance.pk:
            parents = parents.exclude(pk__in=self.instance.descendant_ids())
        self.fields["parent"].queryset = parents.select_related("parent__parent")
        self.fields["parent"].required = False
        self.fields["slug"].required = False


class BrandForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Brand
        fields = ["name", "slug"]
        help_texts = {"slug": "Leave blank to generate from the name."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False


class MaterialForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Material
        fields = ["name"]


class SizeForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Size
        fields = ["name", "sort_order"]


class ColorForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Color
        fields = ["name", "hex_code", "sort_order"]
        widgets = {"hex_code": forms.TextInput(attrs={"type": "color"})}


class SizeChartForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = SizeChart
        fields = ["category", "name", "content"]
        widgets = {"content": forms.Textarea(attrs={"rows": 8, "class": "font-monospace"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.select_related("parent__parent")


class ProductForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Product
        fields = ["name", "slug", "category", "brand", "materials", "base_price", "description", "is_active"]
        widgets = {
            "materials": forms.CheckboxSelectMultiple,
            "description": forms.Textarea(attrs={"rows": 5}),
        }
        help_texts = {"slug": "Leave blank to generate from the name."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["slug"].required = False
        self.fields["category"].queryset = Category.objects.select_related("parent__parent")


class MultipleImageInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleImageField(forms.ImageField):
    """Accepts several images in one upload (FR-S02: multiple images)."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleImageInput(attrs={"accept": "image/*"}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return [single(data, initial)]


class ProductImageUploadForm(BootstrapFormMixin, forms.Form):
    images = MultipleImageField(help_text="JPEG/PNG/WebP, up to 5 MB each.")
    color = forms.ModelChoiceField(queryset=Color.objects.all(), required=False,
                                   help_text="Optional: the color these images show.")

    def clean_images(self):
        images = self.cleaned_data["images"]
        for image in images:
            validate_image_size(image)
        return images

    def save(self, product):
        has_primary = product.images.filter(is_primary=True).exists()
        created = []
        for i, image in enumerate(self.cleaned_data["images"]):
            created.append(ProductImage.objects.create(
                product=product, image=image, color=self.cleaned_data["color"],
                is_primary=(not has_primary and i == 0),
            ))
        return created


class VariantGenerateForm(BootstrapFormMixin, forms.Form):
    sizes = forms.ModelMultipleChoiceField(queryset=Size.objects.all(), widget=forms.CheckboxSelectMultiple)
    colors = forms.ModelMultipleChoiceField(queryset=Color.objects.all(), widget=forms.CheckboxSelectMultiple)
    price_delta = forms.DecimalField(label="Default price adjustment", max_digits=10, decimal_places=2,
                                     initial=Decimal("0.00"),
                                     help_text="Added to the base price of every new variant.")
    safety_level = forms.IntegerField(min_value=0, initial=5, help_text="Low-stock alert threshold.")


class VariantForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = ProductVariant
        fields = ["price_delta", "safety_level", "is_active"]
