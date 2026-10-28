from datetime import timedelta

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.testing import PASSWORD, make_user

from .models import Address, User
from .services import AccountRuleError, BackofficeAccountService


class LockoutTests(TestCase):
    """FR-C01: five consecutive failures lock the account for 15 minutes."""

    def setUp(self):
        self.user = make_user("buyer@example.com")
        self.url = reverse("accounts:login")

    def _attempt(self, password):
        return self.client.post(self.url, {"email": "buyer@example.com", "password": password})

    def test_fifth_failure_locks_account(self):
        for _ in range(4):
            self._attempt("wrong")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 4)
        self.assertIsNone(self.user.locked_until)

        response = self._attempt("wrong")
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_locked())
        self.assertContains(response, "locked until")

    def test_locked_account_rejects_correct_password(self):
        for _ in range(5):
            self._attempt("wrong")
        response = self._attempt(PASSWORD)
        self.assertContains(response, "locked until")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lock_expires_after_fifteen_minutes(self):
        self.user.failed_login_count = 5
        self.user.locked_until = timezone.now() - timedelta(seconds=1)
        self.user.save()
        response = self._attempt(PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)

    def test_success_resets_counter(self):
        self._attempt("wrong")
        self._attempt(PASSWORD)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_count, 0)

    def test_lockout_applies_to_backoffice_accounts(self):
        make_user("staff@example.com", role=User.Role.STAFF)
        for _ in range(5):
            self.client.post(self.url, {"email": "staff@example.com", "password": "nope"})
        self.assertTrue(User.objects.get(email="staff@example.com").is_locked())


class RegistrationTests(TestCase):
    def _register(self, email):
        return self.client.post(reverse("accounts:register"), {
            "email": email, "first_name": "New", "last_name": "Buyer", "phone": "012",
            "password1": PASSWORD, "password2": PASSWORD,
        })

    def test_register_creates_customer_and_signs_in(self):
        response = self._register("new@example.com")
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(email="new@example.com")
        self.assertEqual(user.role, User.Role.CUSTOMER)
        self.assertIn("_auth_user_id", self.client.session)

    @override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.PBKDF2PasswordHasher"])
    def test_passwords_stored_as_pbkdf2(self):
        """NFR-02. (The rest of the suite uses a fast hasher for speed.)"""
        user = make_user("hash@example.com")
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))

    def test_duplicate_email_rejected_case_insensitively(self):
        make_user("taken@example.com")
        response = self._register("TAKEN@example.com")
        self.assertContains(response, "already exists")
        self.assertEqual(User.objects.filter(email__iexact="taken@example.com").count(), 1)


class AddressTests(TestCase):
    def test_single_default_address(self):
        user = make_user("a@example.com")
        first = Address.objects.create(user=user, recipient="A", phone="1", province="Kandal",
                                       district="D", line_1="L")
        second = Address.objects.create(user=user, recipient="B", phone="2", province="Kep",
                                        district="D", line_1="L")
        first.make_default()
        second.make_default()
        first.refresh_from_db()
        self.assertFalse(first.is_default)
        self.assertEqual(user.addresses.filter(is_default=True).count(), 1)

    def test_customer_cannot_edit_another_customers_address(self):
        owner = make_user("owner@example.com")
        other = make_user("other@example.com")
        address = Address.objects.create(user=owner, recipient="A", phone="1", province="Kandal",
                                          district="D", line_1="L")
        self.client.force_login(other)
        response = self.client.get(reverse("accounts:address_update", args=[address.pk]))
        self.assertEqual(response.status_code, 404)


class BackofficeAccountRuleTests(TestCase):
    """FR-A02 / FR-A03: no self-deactivation, never zero active admins."""

    def setUp(self):
        self.admin = make_user("admin@example.com", role=User.Role.ADMIN)
        request = RequestFactory().get("/")
        self.service = BackofficeAccountService(self.admin, request)

    def test_cannot_deactivate_self(self):
        with self.assertRaisesMessage(AccountRuleError, "own account"):
            self.service.set_active(self.admin, False)

    def test_cannot_demote_last_admin(self):
        with self.assertRaisesMessage(AccountRuleError, "no active admin"):
            self.service.change_role(self.admin, User.Role.STAFF)

    def test_can_deactivate_other_admin_when_one_remains(self):
        other = make_user("admin2@example.com", role=User.Role.ADMIN)
        self.service.set_active(other, False)
        other.refresh_from_db()
        self.assertFalse(other.is_active)

    def test_customers_are_not_managed_here(self):
        customer = make_user("c@example.com")
        with self.assertRaises(AccountRuleError):
            self.service.change_role(customer, User.Role.ADMIN)

    def test_created_account_gets_reset_link(self):
        from django.core import mail
        from .forms import BackofficeAccountForm
        form = BackofficeAccountForm(data={"email": "new.staff@example.com", "first_name": "N",
                                           "last_name": "S", "phone": "", "role": "STAFF"})
        self.assertTrue(form.is_valid(), form.errors)
        user, link = self.service.create(form)
        self.assertEqual(user.role, User.Role.STAFF)
        self.assertIn("/account/password/reset/", link)
        self.assertEqual(len(mail.outbox), 1)


class RoleAccessTests(TestCase):
    """FR-X01 / NFR-03: back-office needs Staff; account management needs Admin."""

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("reporting:dashboard"))
        self.assertRedirects(response, f"{reverse('accounts:login')}?next={reverse('reporting:dashboard')}")

    def test_customer_forbidden_from_backoffice(self):
        self.client.force_login(make_user("c@example.com"))
        self.assertEqual(self.client.get(reverse("reporting:dashboard")).status_code, 403)

    def test_staff_can_open_dashboard_but_not_account_management(self):
        self.client.force_login(make_user("s@example.com", role=User.Role.STAFF))
        self.assertEqual(self.client.get(reverse("reporting:dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("accounts_bo:account_list")).status_code, 403)

    def test_admin_can_manage_accounts(self):
        self.client.force_login(make_user("a@example.com", role=User.Role.ADMIN))
        self.assertEqual(self.client.get(reverse("accounts_bo:account_list")).status_code, 200)
