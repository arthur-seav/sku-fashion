from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import CreateView, DeleteView, FormView, ListView, UpdateView

from core.permissions import AdminRequiredMixin, CustomerRequiredMixin

from .forms import (AddressForm, BackofficeAccountForm, LoginForm, ProfileForm,
                    RegistrationForm, RoleChangeForm)
from .models import Address, User
from .services import AccountRuleError, BackofficeAccountService, LoginService


def landing_url_for(user):
    if user.is_backoffice:
        return reverse("reporting:dashboard")
    return reverse("core:home")


# --------------------------------------------------------------------------
# Sign in / out / register (UC-01, UC-02)
# --------------------------------------------------------------------------
class LoginView(FormView):
    template_name = "accounts/login.html"
    form_class = LoginForm

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(landing_url_for(request.user))
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        result = LoginService(self.request).login(form.cleaned_data["email"], form.cleaned_data["password"])
        if not result.ok:
            form.add_error(None, result.error)
            return self.form_invalid(form)
        messages.success(self.request, f"Welcome back, {result.user.first_name}.")
        next_url = self.request.POST.get("next") or self.request.GET.get("next")
        if next_url and url_has_allowed_host_and_scheme(next_url, {self.request.get_host()}):
            return redirect(next_url)
        return redirect(landing_url_for(result.user))


class LogoutView(auth_views.LogoutView):
    next_page = reverse_lazy("core:home")


class RegisterView(CreateView):
    template_name = "accounts/register.html"
    form_class = RegistrationForm

    def form_valid(self, form):
        user = form.save()
        login(self.request, user, backend="accounts.backends.LockoutAwareBackend")
        messages.success(self.request, "Your account has been created.")
        return redirect("core:home")


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "accounts/password_change.html"
    success_url = reverse_lazy("accounts:profile")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        return form

    def form_valid(self, form):
        messages.success(self.request, "Your password has been changed.")
        return super().form_valid(form)

    def get_template_names(self):
        if self.request.user.is_backoffice:
            return ["accounts/backoffice/password_change.html"]
        return [self.template_name]


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = "accounts/password_reset_confirm.html"
    success_url = reverse_lazy("accounts:login")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        for field in form.fields.values():
            field.widget.attrs["class"] = "form-control"
        return form

    def form_valid(self, form):
        response = super().form_valid(form)
        form.user.reset_failed_logins()
        messages.success(self.request, "Your password has been set. You can sign in now.")
        return response


# --------------------------------------------------------------------------
# Profile and address book (UC-06)
# --------------------------------------------------------------------------
class ProfileView(LoginRequiredMixin, UpdateView):
    template_name = "accounts/profile.html"
    form_class = ProfileForm
    success_url = reverse_lazy("accounts:profile")

    def get_object(self, queryset=None):
        return self.request.user

    def form_valid(self, form):
        messages.success(self.request, "Profile updated.")
        return super().form_valid(form)


class AddressQuerysetMixin(CustomerRequiredMixin):
    """Customers only ever see and change their own addresses."""

    def get_queryset(self):
        return Address.objects.filter(user=self.request.user)


class AddressListView(AddressQuerysetMixin, ListView):
    template_name = "accounts/address_list.html"
    context_object_name = "addresses"


class AddressSaveMixin:
    form_class = AddressForm
    template_name = "accounts/address_form.html"
    success_url = reverse_lazy("accounts:address_list")

    def form_valid(self, form):
        form.instance.user = self.request.user
        is_first = not Address.objects.filter(user=self.request.user).exclude(pk=form.instance.pk).exists()
        response = super().form_valid(form)
        if form.cleaned_data["is_default"] or is_first:
            self.object.make_default()
        messages.success(self.request, "Address saved.")
        return response


class AddressCreateView(AddressQuerysetMixin, AddressSaveMixin, CreateView):
    pass


class AddressUpdateView(AddressQuerysetMixin, AddressSaveMixin, UpdateView):
    pass


class AddressDeleteView(AddressQuerysetMixin, DeleteView):
    template_name = "accounts/address_confirm_delete.html"
    success_url = reverse_lazy("accounts:address_list")

    def form_valid(self, form):
        was_default = self.object.is_default
        response = super().form_valid(form)
        if was_default:
            replacement = Address.objects.filter(user=self.request.user).first()
            if replacement:
                replacement.make_default()
        messages.success(self.request, "Address deleted.")
        return response


class AddressMakeDefaultView(AddressQuerysetMixin, View):
    def post(self, request, pk):
        get_object_or_404(self.get_queryset(), pk=pk).make_default()
        messages.success(request, "Default address updated.")
        return redirect("accounts:address_list")


# --------------------------------------------------------------------------
# Back-office account management (UC-20, Admin only)
# --------------------------------------------------------------------------
class BackofficeAccountListView(AdminRequiredMixin, ListView):
    template_name = "accounts/backoffice/account_list.html"
    context_object_name = "accounts"
    paginate_by = 20

    def get_queryset(self):
        qs = User.objects.filter(role__in=[User.Role.STAFF, User.Role.ADMIN])
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))
        role = self.request.GET.get("role")
        if role in (User.Role.STAFF, User.Role.ADMIN):
            qs = qs.filter(role=role)
        status = self.request.GET.get("status")
        if status in ("active", "inactive"):
            qs = qs.filter(is_active=(status == "active"))
        return qs.order_by("-is_active", "role", "email")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["role_form"] = RoleChangeForm()
        return ctx


class BackofficeAccountCreateView(AdminRequiredMixin, CreateView):
    template_name = "accounts/backoffice/account_form.html"
    form_class = BackofficeAccountForm

    def form_valid(self, form):
        user, link = BackofficeAccountService(self.request.user, self.request).create(form)
        messages.success(self.request, f"Account {user.email} created. A set-password link was emailed.")
        _flash_dev_link(self.request, link)
        return redirect("accounts_bo:account_list")


class BackofficeAccountActionView(AdminRequiredMixin, View):
    """POST-only actions: activate, deactivate, change role, reset password."""

    def post(self, request, pk, action):
        target = get_object_or_404(User, pk=pk)
        service = BackofficeAccountService(request.user, request)
        try:
            if action == "deactivate":
                service.set_active(target, False)
                messages.success(request, f"{target.email} has been deactivated.")
            elif action == "activate":
                service.set_active(target, True)
                messages.success(request, f"{target.email} has been reactivated.")
            elif action == "role":
                form = RoleChangeForm(request.POST)
                if form.is_valid():
                    service.change_role(target, form.cleaned_data["role"])
                    messages.success(request, f"{target.email} is now {target.get_role_display()}.")
            elif action == "reset-password":
                link = service.reset_password(target)
                messages.success(request, f"A password reset link was emailed to {target.email}.")
                _flash_dev_link(request, link)
        except AccountRuleError as exc:
            messages.error(request, str(exc))
        return redirect("accounts_bo:account_list")


def _flash_dev_link(request, link):
    """Emails go to the console in development; show the link for demos."""
    from django.conf import settings
    if settings.DEBUG:
        messages.info(request, f"[DEBUG] Set-password link: {link}")
