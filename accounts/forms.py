from django import forms
from django.contrib.auth import password_validation

from core.forms import BootstrapFormMixin

from .models import Address, User


class EmailUniqueMixin:
    """Duplicate email addresses are rejected, case-insensitively (FR-G01)."""

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        qs = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("An account with this email address already exists.")
        return email


class RegistrationForm(BootstrapFormMixin, EmailUniqueMixin, forms.ModelForm):
    password1 = forms.CharField(label="Password", widget=forms.PasswordInput,
                                help_text=password_validation.password_validators_help_text_html())
    password2 = forms.CharField(label="Confirm password", widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone"]

    def clean(self):
        cleaned = super().clean()
        p1, p2 = cleaned.get("password1"), cleaned.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "The two passwords do not match.")
        if p1:
            # Validate against a temporary user so similarity checks work.
            candidate = User(email=cleaned.get("email", ""),
                             first_name=cleaned.get("first_name", ""),
                             last_name=cleaned.get("last_name", ""))
            try:
                password_validation.validate_password(p1, candidate)
            except forms.ValidationError as exc:
                self.add_error("password1", exc)
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        user.role = User.Role.CUSTOMER
        user.set_password(self.cleaned_data["password1"])
        if commit:
            user.save()
        return user


class LoginForm(BootstrapFormMixin, forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"autofocus": True}))
    password = forms.CharField(widget=forms.PasswordInput)


class ProfileForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]


class AddressForm(BootstrapFormMixin, forms.ModelForm):
    class Meta:
        model = Address
        fields = ["recipient", "phone", "province", "district", "line_1", "is_default"]
        labels = {"is_default": "Use as default delivery address"}


# --------------------------------------------------------------------------
# Back-office account management (Admin only)
# --------------------------------------------------------------------------
BACKOFFICE_ROLE_CHOICES = [
    (User.Role.STAFF, User.Role.STAFF.label),
    (User.Role.ADMIN, User.Role.ADMIN.label),
]


class BackofficeAccountForm(BootstrapFormMixin, EmailUniqueMixin, forms.ModelForm):
    """FR-A01: email, full name and initial role (Staff or Admin)."""

    role = forms.ChoiceField(choices=BACKOFFICE_ROLE_CHOICES, initial=User.Role.STAFF)

    class Meta:
        model = User
        fields = ["email", "first_name", "last_name", "phone", "role"]


class RoleChangeForm(BootstrapFormMixin, forms.Form):
    role = forms.ChoiceField(choices=BACKOFFICE_ROLE_CHOICES)
