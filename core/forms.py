"""Form helpers shared by every app."""

from django import forms


class BootstrapFormMixin:
    """Adds Bootstrap 5 classes to every widget so templates can render
    any form with the shared `partials/form_fields.html` include."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, (forms.CheckboxInput,)):
                css = "form-check-input"
            elif isinstance(widget, (forms.CheckboxSelectMultiple, forms.RadioSelect)):
                css = ""
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                css = "form-select"
            else:
                css = "form-control"
            if css:
                existing = widget.attrs.get("class", "")
                widget.attrs["class"] = f"{existing} {css}".strip()


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class DateTimeInput(forms.DateTimeInput):
    input_type = "datetime-local"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%dT%H:%M")
