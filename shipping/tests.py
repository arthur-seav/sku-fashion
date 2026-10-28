from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from core.testing import make_staff

from .models import ShippingMethod, ShippingRate
from .services import ShippingQuoteService


class ShippingQuoteTests(TestCase):
    def setUp(self):
        self.express = ShippingMethod.objects.create(name="Express", base_fee=Decimal("5.00"),
                                                     free_threshold=Decimal("100.00"))
        ShippingRate.objects.create(method=self.express, province="Phnom Penh", fee=Decimal("2.00"))
        self.pickup = ShippingMethod.objects.create(name="Store pick-up", base_fee=Decimal("0.00"))
        self.service = ShippingQuoteService()

    def test_province_rate_overrides_base_fee(self):
        self.assertEqual(self.service.quote(self.express, "Phnom Penh", Decimal("20")).fee, Decimal("2.00"))
        self.assertEqual(self.service.quote(self.express, "Kampot", Decimal("20")).fee, Decimal("5.00"))

    def test_free_threshold(self):
        quote = self.service.quote(self.express, "Kampot", Decimal("100.00"))
        self.assertEqual((quote.fee, quote.reason), (Decimal("0.00"), "free threshold"))

    def test_store_pickup_is_free(self):
        self.assertEqual(self.service.quote(self.pickup, "Kampot", Decimal("1")).fee, Decimal("0.00"))


class ShippingBackofficeTests(TestCase):
    def test_lists_render(self):
        self.client.force_login(make_staff())
        ShippingMethod.objects.create(name="Standard", base_fee=Decimal("3"))
        self.assertContains(self.client.get(reverse("shipping_bo:method_list")), "Standard")
        self.assertEqual(self.client.get(reverse("shipping_bo:rate_list")).status_code, 200)
