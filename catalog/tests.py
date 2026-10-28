from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from core.testing import make_product, make_staff

from .models import Category, Color, ProductVariant, Size
from .services import VariantGenerator


class CategoryTreeTests(TestCase):
    """FR-S01: up to three levels."""

    def test_levels_are_derived_from_parent(self):
        women = Category.objects.create(name="Women")
        tops = Category.objects.create(name="Tops", parent=women)
        tees = Category.objects.create(name="T-Shirts", parent=tops)
        self.assertEqual((women.level, tops.level, tees.level), (1, 2, 3))
        self.assertEqual(str(tees), "Women › Tops › T-Shirts")

    def test_fourth_level_rejected(self):
        a = Category.objects.create(name="A")
        b = Category.objects.create(name="B", parent=a)
        c = Category.objects.create(name="C", parent=b)
        with self.assertRaises(ValidationError):
            Category(name="D", parent=c).full_clean()

    def test_moving_subtree_cannot_exceed_depth(self):
        a = Category.objects.create(name="A")
        b = Category.objects.create(name="B", parent=a)
        x = Category.objects.create(name="X")
        Category.objects.create(name="Y", parent=x)
        x.parent = b  # X would be level 3 and Y level 4
        with self.assertRaises(ValidationError):
            x.full_clean()

    def test_cannot_parent_to_own_descendant(self):
        a = Category.objects.create(name="A")
        b = Category.objects.create(name="B", parent=a)
        a.parent = b
        with self.assertRaises(ValidationError):
            a.full_clean()

    def test_size_chart_inherited_from_ancestor(self):
        from .models import SizeChart
        women = Category.objects.create(name="Women")
        tops = Category.objects.create(name="Tops", parent=women)
        chart = SizeChart.objects.create(category=women, name="Women sizes", content="Size | Chest\nS | 80")
        self.assertEqual(tops.size_chart_or_inherited(), chart)
        self.assertEqual(chart.rows(), [["Size", "Chest"], ["S", "80"]])


class VariantGeneratorTests(TestCase):
    """UC-13 / FR-S03."""

    def setUp(self):
        self.product = make_product()
        self.sizes = [Size.objects.create(name=n, sort_order=i) for i, n in enumerate(["S", "M", "L"])]
        self.colors = [Color.objects.create(name="Black", hex_code="#000000"),
                       Color.objects.create(name="White", hex_code="#FFFFFF")]

    def test_generates_every_combination_with_zero_stock(self):
        created, skipped = VariantGenerator(self.product).generate(self.sizes, self.colors, Decimal("2.00"))
        self.assertEqual((len(created), skipped), (6, 0))
        self.assertTrue(all(v.stock_qty == 0 for v in created))
        self.assertTrue(all(v.price == Decimal("22.00") for v in created))
        self.assertEqual(len({v.sku for v in created}), 6)
        self.assertRegex(created[0].sku, r"^P\d{4}-BLA-S$")

    def test_existing_combinations_are_skipped_and_kept(self):
        VariantGenerator(self.product).generate(self.sizes[:1], self.colors[:1], Decimal("5.00"))
        original = ProductVariant.objects.get()
        created, skipped = VariantGenerator(self.product).generate(self.sizes, self.colors)
        self.assertEqual((len(created), skipped), (5, 1))
        original.refresh_from_db()
        self.assertEqual(original.price_delta, Decimal("5.00"))

    def test_preview_writes_nothing(self):
        combos = VariantGenerator(self.product).preview(self.sizes, self.colors)
        self.assertEqual(len(combos), 6)
        self.assertFalse(ProductVariant.objects.exists())


class BackofficeCatalogViewTests(TestCase):
    def setUp(self):
        self.client.force_login(make_staff())

    def test_crud_lists_render(self):
        for name in ["category", "brand", "material", "size", "color", "sizechart", "product"]:
            response = self.client.get(reverse(f"catalog_bo:{name}_list"))
            self.assertEqual(response.status_code, 200, name)

    def test_create_brand_generates_slug(self):
        self.client.post(reverse("catalog_bo:brand_create"), {"name": "Mekong Denim", "slug": ""})
        from .models import Brand
        self.assertEqual(Brand.objects.get().slug, "mekong-denim")

    def test_generate_variants_preview_then_confirm(self):
        product = make_product()
        size = Size.objects.create(name="M")
        color = Color.objects.create(name="Navy", hex_code="#000080")
        url = reverse("catalog_bo:variant_generate", args=[product.pk])
        data = {"sizes": [size.pk], "colors": [color.pk], "price_delta": "0", "safety_level": "3"}
        preview = self.client.post(url, {**data, "action": "preview"})
        self.assertContains(preview, "New · stock 0")
        self.assertFalse(ProductVariant.objects.exists())
        self.client.post(url, {**data, "action": "confirm"})
        self.assertEqual(ProductVariant.objects.get().safety_level, 3)

    def test_product_search_matches_sku(self):
        product = make_product(name="Linen Shirt")
        VariantGenerator(product).generate([Size.objects.create(name="L")],
                                           [Color.objects.create(name="Sand", hex_code="#C2B280")])
        sku = ProductVariant.objects.get().sku
        response = self.client.get(reverse("catalog_bo:product_list"), {"q": sku})
        self.assertContains(response, "Linen Shirt")
