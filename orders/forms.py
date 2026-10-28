from django import forms

from core.forms import BootstrapFormMixin
from core.provinces import PROVINCE_CHOICES
from payments.providers import registry
from shipping.models import ShippingMethod


class CheckoutForm(BootstrapFormMixin, forms.Form):
    recipient = forms.CharField(max_length=150)
    phone = forms.CharField(max_length=30)
    province = forms.ChoiceField(choices=PROVINCE_CHOICES)
    district = forms.CharField(max_length=100)
    line_1 = forms.CharField(label="Address line", max_length=255)
    shipping_method = forms.ModelChoiceField(queryset=ShippingMethod.objects.none(), widget=forms.RadioSelect,
                                             empty_label=None)
    coupon_code = forms.CharField(max_length=30, required=False, label="Coupon code")
    payment_method = forms.ChoiceField(choices=(), widget=forms.RadioSelect)

    ADDRESS_FIELDS = ["recipient", "phone", "province", "district", "line_1"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["shipping_method"].queryset = ShippingMethod.objects.filter(is_active=True)
        self.fields["payment_method"].choices = registry.choices()

    @property
    def address(self):
        return {name: self.cleaned_data[name] for name in self.ADDRESS_FIELDS}

    @staticmethod
    def initial_from_address(address):
        if address is None:
            return {}
        return {name: getattr(address, name) for name in CheckoutForm.ADDRESS_FIELDS}
