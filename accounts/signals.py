from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.dispatch import receiver

from .models import User


@receiver(user_login_failed)
def count_failed_login(sender, credentials, request=None, **kwargs):
    """Record every failed attempt against the account (FR-C01)."""
    email = credentials.get("email") or credentials.get("username")
    if not email:
        return
    user = User.objects.filter(email__iexact=email).first()
    # A locked or deactivated account is rejected anyway; counting those
    # attempts would only keep extending the lock.
    if user is None or user.is_locked() or not user.is_active:
        return
    user.register_failed_login()


@receiver(user_logged_in)
def reset_failed_logins(sender, request, user, **kwargs):
    user.reset_failed_logins()
