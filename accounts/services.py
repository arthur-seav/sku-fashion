from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

from .models import User


class AccountRuleError(Exception):
    """A requested account change violates a business rule (FR-A02/A03)."""


@dataclass
class LoginResult:
    user: User | None = None
    error: str = ""

    @property
    def ok(self):
        return self.user is not None


class LoginService:
    """Email + password sign-in with the five-attempt lockout (FR-C01, FR-X01).

    Failed attempts are counted by the `user_login_failed` signal, so the rule
    also covers the Django admin login. This class turns the outcome into a
    message the user can act on.
    """

    def __init__(self, request):
        self.request = request

    def login(self, email, password):
        account = User.objects.filter(email__iexact=email).first()
        if account and account.is_locked():
            return LoginResult(error=self._locked_message(account))

        user = authenticate(self.request, email=email, password=password)
        if user is None:
            if account:
                account.refresh_from_db()
                if not account.is_active:
                    return LoginResult(error="This account has been deactivated.")
                if account.is_locked():
                    return LoginResult(error=self._locked_message(account))
                remaining = User.LOCKOUT_THRESHOLD - account.failed_login_count
                return LoginResult(
                    error=f"Invalid email or password. {remaining} attempt(s) left before "
                          f"the account is locked for 15 minutes."
                )
            return LoginResult(error="Invalid email or password.")

        login(self.request, user)
        return LoginResult(user=user)

    @staticmethod
    def _locked_message(account):
        until = timezone.localtime(account.locked_until).strftime("%H:%M")
        return f"Too many failed attempts. This account is locked until {until}."


class PasswordResetService:
    """Builds a one-time reset link and emails it (console backend in dev)."""

    def __init__(self, request):
        self.request = request

    def build_link(self, user):
        uid = urlsafe_base64_encode(force_bytes(user.pk))
        token = default_token_generator.make_token(user)
        path = reverse("accounts:password_reset_confirm", kwargs={"uidb64": uid, "token": token})
        return self.request.build_absolute_uri(path)

    def send(self, user, intro="A password reset was requested for your account."):
        link = self.build_link(user)
        send_mail(
            subject=f"[{settings.STORE_NAME}] Set your password",
            message=f"Hello {user.full_name},\n\n{intro}\nSet a new password here:\n{link}\n",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
        )
        return link


class BackofficeAccountService:
    """Back-office account management rules (FR-A01 … FR-A04, FR-X13)."""

    def __init__(self, acting_user, request):
        self.acting_user = acting_user
        self.request = request

    def create(self, form):
        """FR-A01. The account gets a random password and a set-password link."""
        with transaction.atomic():
            user = form.save(commit=False)
            user.set_password(get_random_string(32))
            user.save()
        link = PasswordResetService(self.request).send(
            user, intro="A back-office account has been created for you."
        )
        return user, link

    def set_active(self, target, active):
        """FR-A02. Deactivated accounts keep their recorded actions."""
        self._ensure_backoffice(target)
        if not active:
            if target.pk == self.acting_user.pk:
                raise AccountRuleError("You cannot deactivate your own account.")
            with transaction.atomic():
                if target.is_admin_role and target.is_active:
                    self._ensure_other_active_admin(target)
                target.is_active = False
                target.save(update_fields=["is_active"])
        else:
            target.is_active = True
            target.save(update_fields=["is_active"])
        return target

    def change_role(self, target, role):
        """FR-A03. Staff <-> Admin; never leave the system without an admin."""
        self._ensure_backoffice(target)
        if role not in (User.Role.STAFF, User.Role.ADMIN):
            raise AccountRuleError("Role must be Staff or Admin.")
        with transaction.atomic():
            if target.is_admin_role and role == User.Role.STAFF and target.is_active:
                self._ensure_other_active_admin(target)
            target.role = role
            target.save(update_fields=["role"])
        return target

    def reset_password(self, target):
        """FR-A04. The admin never sees or needs the current password."""
        self._ensure_backoffice(target)
        return PasswordResetService(self.request).send(
            target, intro="An administrator has reset your password."
        )

    # ---- rules -------------------------------------------------------------
    @staticmethod
    def _ensure_backoffice(target):
        if not target.is_backoffice:
            raise AccountRuleError("Only back-office accounts can be managed here.")

    @staticmethod
    def _ensure_other_active_admin(target):
        # Lock admin rows so two admins cannot demote each other concurrently.
        others = (User.objects.select_for_update()
                  .filter(role=User.Role.ADMIN, is_active=True)
                  .exclude(pk=target.pk))
        if not list(others):
            raise AccountRuleError("This change would leave no active admin account.")
