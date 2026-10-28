from django.contrib.auth.signals import user_logged_in
from django.dispatch import receiver

from .services import CartService


@receiver(user_logged_in)
def merge_guest_cart_on_login(sender, request, user, **kwargs):
    """FR-X02: the guest's session cart joins the customer's account cart."""
    if request is None or not hasattr(request, "session"):
        return
    guest_cart_id = request.session.pop(CartService.SESSION_KEY, None)
    if guest_cart_id:
        CartService.merge_guest_cart(guest_cart_id, user)
