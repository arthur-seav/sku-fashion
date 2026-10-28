from django import forms

from core.forms import BootstrapFormMixin

REASON_SUGGESTIONS = [
    "Received from supplier",
    "Stock count correction",
    "Damaged / defective",
    "Returned to supplier",
    "Customer return restocked",
]


class StockAdjustmentForm(BootstrapFormMixin, forms.Form):
    DIRECTION_CHOICES = [("in", "Add stock (IN)"), ("out", "Remove stock (OUT)")]

    direction = forms.ChoiceField(choices=DIRECTION_CHOICES, widget=forms.RadioSelect, initial="in")
    quantity = forms.IntegerField(min_value=1)
    reason = forms.CharField(max_length=255, widget=forms.TextInput(attrs={"list": "reason-suggestions"}),
                             help_text="Required — recorded in the movement history.")

    @property
    def signed_change(self):
        qty = self.cleaned_data["quantity"]
        return qty if self.cleaned_data["direction"] == "in" else -qty
