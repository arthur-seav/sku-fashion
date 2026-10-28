from django import forms

from core.forms import BootstrapFormMixin

from .services import RATING_LABELS


class ReviewForm(BootstrapFormMixin, forms.Form):
    rating = forms.TypedChoiceField(choices=[(n, f"{n} · {label}") for n, label in RATING_LABELS.items()],
                                    coerce=int, widget=forms.RadioSelect,
                                    error_messages={"required": "Choose a rating from 1 to 5 stars."})
    comment = forms.CharField(required=False, max_length=1000, widget=forms.Textarea(attrs={"rows": 5}),
                              help_text="Fit, fabric, colour, how it washed — anything another shopper would "
                                        "want to know. Up to 1,000 characters.")


class RejectForm(BootstrapFormMixin, forms.Form):
    note = forms.CharField(max_length=255, label="Reason")
