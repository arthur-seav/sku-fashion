from .services import CartService


def cart(request):
    """Item count for the storefront navbar."""
    if request.path.startswith(("/backoffice/", "/django-admin/")):
        return {}
    return {"cart_count": CartService(request, pricer=lambda v: None).count()}
