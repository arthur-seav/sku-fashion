from django.test import TestCase
from django.urls import reverse

from core.navigation import BACKOFFICE_NAV
from core.testing import make_staff, make_user
from accounts.models import User


class NavigationTests(TestCase):
    def test_every_sidebar_entry_resolves(self):
        """The sidebar hides entries whose URL does not resolve; make sure none are missing."""
        for group in BACKOFFICE_NAV:
            for item in group.items:
                reverse(item.url_name)  # raises NoReverseMatch if a URL name is wrong

    def test_sidebar_hides_admin_entries_from_staff(self):
        self.client.force_login(make_staff())
        page = self.client.get(reverse("reporting:dashboard"))
        self.assertContains(page, "Stock levels")
        self.assertNotContains(page, "Back-office accounts")
        self.client.force_login(make_user("a@example.com", role=User.Role.ADMIN))
        self.assertContains(self.client.get(reverse("reporting:dashboard")), "Back-office accounts")

    def test_every_backoffice_list_page_renders(self):
        self.client.force_login(make_user("admin@example.com", role=User.Role.ADMIN))
        for group in BACKOFFICE_NAV:
            for item in group.items:
                self.assertEqual(self.client.get(reverse(item.url_name)).status_code, 200, item.url_name)

    def test_seed_demo_loads_and_refuses_to_run_twice(self):
        from io import StringIO

        from django.core.management import CommandError, call_command
        from django.test import override_settings
        from django.utils import timezone

        from orders.models import Order, OrderStatusHistory

        with override_settings(MEDIA_ROOT="/home/hermes/.hermes/cache/scratch/sku-media-test"):
            call_command("seed_demo", stdout=StringIO())
            self.assertGreater(Order.objects.count(), 20)
            self.assertTrue(Order.objects.filter(status="PENDING_PAYMENT", payments__receipt_image__gt="").exists())
            self.assertFalse(OrderStatusHistory.objects.filter(created_at__gt=timezone.now()).exists())
            with self.assertRaises(CommandError):
                call_command("seed_demo", stdout=StringIO())

    def test_storefront_pages_render(self):
        for name in ["core:home", "catalog:product_list", "cart:detail", "accounts:login", "accounts:register"]:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
