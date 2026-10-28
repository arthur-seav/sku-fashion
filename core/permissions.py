"""Role-based access mixins shared by every back-office and customer view.

FR-X01: back-office functions require the Staff role; account management
requires the Admin role. NFR-03: every back-office view enforces this check.

Anonymous users are redirected to the login page; signed-in users without
the required role receive 403 (UserPassesTestMixin's default behavior).
"""

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Base class: subclasses implement `has_role(user)`."""

    def has_role(self, user):
        raise NotImplementedError

    def test_func(self):
        return self.has_role(self.request.user)


class CustomerRequiredMixin(RoleRequiredMixin):
    def has_role(self, user):
        return user.is_customer


class StaffRequiredMixin(RoleRequiredMixin):
    """Staff or Admin — Admin inherits every Staff capability."""

    def has_role(self, user):
        return user.is_backoffice


class AdminRequiredMixin(RoleRequiredMixin):
    def has_role(self, user):
        return user.is_admin_role
