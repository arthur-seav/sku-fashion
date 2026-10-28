"""Factories shared by every app's tests — one place to change when a
model gains a required field."""

from decimal import Decimal

from accounts.models import User
from catalog.models import Brand, Category, Color, Product, ProductVariant, Size

PASSWORD = "Str0ng-pass-123"


def make_user(email="buyer@example.com", role=User.Role.CUSTOMER, **extra):
    return User.objects.create_user(email=email, password=PASSWORD, first_name="Test",
                                    last_name="User", role=role, **extra)


def make_staff(email="staff@example.com"):
    return make_user(email, role=User.Role.STAFF)


def make_product(name="Basic Tee", price="20.00", category=None, brand=None, **extra):
    category = category or Category.objects.get_or_create(name="Tops")[0]
    brand = brand or Brand.objects.get_or_create(name="Acme")[0]
    return Product.objects.create(name=name, category=category, brand=brand,
                                  base_price=Decimal(price), **extra)


def make_variant(product=None, color="Black", size="M", stock=10, delta="0.00", safety=5):
    product = product or make_product()
    color_obj = Color.objects.get_or_create(name=color, defaults={"hex_code": "#000000"})[0]
    size_obj = Size.objects.get_or_create(name=size)[0]
    variant = ProductVariant.objects.create(
        product=product, color=color_obj, size=size_obj,
        sku=f"T-{product.pk}-{color}-{size}", price_delta=Decimal(delta), safety_level=safety)
    if stock:
        ProductVariant.objects.filter(pk=variant.pk).update(stock_qty=stock)
        variant.refresh_from_db()
    return variant
