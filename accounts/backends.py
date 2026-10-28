from django.contrib.auth.backends import ModelBackend


class LockoutAwareBackend(ModelBackend):
    """Email + password authentication that refuses locked accounts.

    The lockout rule of FR-C01 applies to every account (FR-X01), including
    sign-ins through the Django admin, so it is enforced here rather than
    only in the storefront login view.
    """

    def user_can_authenticate(self, user):
        return super().user_can_authenticate(user) and not user.is_locked()
