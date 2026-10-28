from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.text import slugify

from core.validators import validate_image_size


def unique_slug(instance, value, field="slug"):
    """Slugify `value` and add -2, -3 … until it is unique for the model."""
    base = slugify(value)[:100] or "item"
    slug, n = base, 2
    model = type(instance)
    while model.objects.filter(**{field: slug}).exclude(pk=instance.pk).exists():
        slug = f"{base}-{n}"
        n += 1
    return slug


class Category(models.Model):
    """A node in the category tree, at most three levels deep (FR-S01)."""

    MAX_LEVEL = 3

    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    level = models.PositiveSmallIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["level", "name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return " › ".join(c.name for c in [*self.ancestors(), self])

    def ancestors(self):
        chain, node = [], self.parent
        while node is not None:
            chain.insert(0, node)
            node = node.parent
        return chain

    def descendant_ids(self, include_self=True):
        ids = [self.pk] if include_self else []
        frontier = [self.pk]
        while frontier:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            ids.extend(frontier)
        return ids

    def subtree_height(self):
        """1 for a leaf, 2 if it has children, 3 if it has grandchildren."""
        if not self.pk:
            return 1
        height, frontier = 1, [self.pk]
        while True:
            frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
            if not frontier:
                return height
            height += 1

    def clean(self):
        if self.parent_id:
            if self.pk and self.parent_id in self.descendant_ids():
                raise ValidationError({"parent": "A category cannot be placed under itself or its children."})
            new_level = self.parent.level + 1
            if new_level + self.subtree_height() - 1 > self.MAX_LEVEL:
                raise ValidationError({"parent": f"Categories can be at most {self.MAX_LEVEL} levels deep."})

    def save(self, *args, **kwargs):
        self.level = self.parent.level + 1 if self.parent_id else 1
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)
        for child in self.children.all():  # keep descendants' levels in step after a move
            if child.level != self.level + 1:
                child.save()

    def size_chart_or_inherited(self):
        """The size chart of this category, or of the nearest ancestor that has one."""
        for node in [self, *reversed(self.ancestors())]:
            chart = getattr(node, "size_chart", None)
            if chart is not None:
                return chart
        return None


class Brand(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)


class Material(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Size(models.Model):
    name = models.CharField(max_length=20, unique=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class Color(models.Model):
    name = models.CharField(max_length=50, unique=True)
    hex_code = models.CharField(max_length=7, default="#000000",
                                validators=[RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Use the form #RRGGBB.")])
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class SizeChart(models.Model):
    """Measurements for a category. `content` holds one row per line with
    columns separated by "|"; the first line is the header."""

    category = models.OneToOneField(Category, on_delete=models.CASCADE, related_name="size_chart")
    name = models.CharField(max_length=100)
    content = models.TextField(help_text="One row per line, columns separated by “|”. "
                                         "The first line is the header, e.g. <code>Size | Chest (cm) | Length (cm)</code>")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def rows(self):
        lines = [line.strip() for line in self.content.splitlines() if line.strip()]
        return [[cell.strip() for cell in line.split("|")] for line in lines]


class Product(models.Model):
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(Brand, on_delete=models.PROTECT, related_name="products")
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    base_price = models.DecimalField(max_digits=10, decimal_places=2,
                                     validators=[MinValueValidator(Decimal("0.00"))])
    is_active = models.BooleanField(default=True, help_text="Inactive products are hidden from the storefront.")
    materials = models.ManyToManyField(Material, through="ProductMaterial", blank=True, related_name="products")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    @property
    def primary_image(self):
        """Uses the prefetched `images` list when available (no extra query)."""
        images = list(self.images.all())
        for image in images:
            if image.is_primary:
                return image
        return images[0] if images else None

    def size_chart(self):
        return self.category.size_chart_or_inherited()


class ProductMaterial(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    material = models.ForeignKey(Material, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "material"], name="uniq_product_material")]


class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/%Y/%m/", validators=[validate_image_size])
    is_primary = models.BooleanField(default=False)
    color = models.ForeignKey(Color, null=True, blank=True, on_delete=models.SET_NULL, related_name="images")

    class Meta:
        ordering = ["-is_primary", "id"]

    def __str__(self):
        return f"Image of {self.product}"

    def make_primary(self):
        ProductImage.objects.filter(product=self.product).exclude(pk=self.pk).update(is_primary=False)
        self.is_primary = True
        self.save(update_fields=["is_primary"])


class ProductVariant(models.Model):
    """A sellable SKU: one size × color combination of a product (FR-S03)."""

    class StockStatus(models.TextChoices):
        IN_STOCK = "IN_STOCK", "In stock"
        LOW = "LOW", "Low stock"
        SOLD_OUT = "SOLD_OUT", "Sold out"

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="variants")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="variants")
    sku = models.CharField("SKU", max_length=64, unique=True)
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"),
                                      help_text="Added to the product's base price (can be negative).")
    stock_qty = models.PositiveIntegerField(default=0, editable=False)
    safety_level = models.PositiveIntegerField(default=5, help_text="Alert when stock falls below this level.")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["product_id", "color__sort_order", "size__sort_order"]
        constraints = [models.UniqueConstraint(fields=["product", "color", "size"], name="uniq_variant_combination")]

    def __str__(self):
        return f"{self.product.name} — {self.spec} ({self.sku})"

    @property
    def spec(self):
        return f"{self.color.name} / {self.size.name}"

    @property
    def price(self):
        return self.product.base_price + self.price_delta

    @property
    def is_sold_out(self):
        return self.stock_qty == 0

    @property
    def is_low_stock(self):
        """Below the safety level (FR-X12). Sold-out variants are also low."""
        return self.stock_qty < self.safety_level

    @property
    def stock_status(self):
        if self.is_sold_out:
            return self.StockStatus.SOLD_OUT
        if self.is_low_stock:
            return self.StockStatus.LOW
        return self.StockStatus.IN_STOCK

    @property
    def is_purchasable(self):
        return self.is_active and self.product.is_active and not self.is_sold_out
