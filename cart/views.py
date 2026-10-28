from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import TemplateView

from catalog.models import ProductVariant

from .services import CartError, CartService


def _quantity(value, default=1):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class CartDetailView(TemplateView):
    template_name = "cart/detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["summary"] = CartService(self.request).summary()
        return ctx


class AddToCartView(View):
    def post(self, request):
        variant_id = request.POST.get("variant")
        if not variant_id:
            messages.error(request, "Please choose a color and size.")
            return self._back(request)
        variant = get_object_or_404(ProductVariant.objects.select_related("product"), pk=variant_id)
        try:
            CartService(request).add(variant, _quantity(request.POST.get("quantity")))
        except CartError as exc:
            messages.error(request, str(exc))
            return self._back(request)
        messages.success(request, f"Added {variant.product.name} ({variant.spec}) to your cart.")
        return redirect("cart:detail")

    @staticmethod
    def _back(request):
        referer = request.META.get("HTTP_REFERER")
        if referer and url_has_allowed_host_and_scheme(referer, {request.get_host()}):
            return redirect(referer)
        return redirect("cart:detail")


class UpdateCartItemView(View):
    def post(self, request, item_id):
        try:
            CartService(request).update(item_id, _quantity(request.POST.get("quantity"), 0))
        except CartError as exc:
            messages.error(request, str(exc))
        return redirect("cart:detail")


class RemoveCartItemView(View):
    def post(self, request, item_id):
        try:
            CartService(request).remove(item_id)
            messages.success(request, "Item removed.")
        except CartError as exc:
            messages.error(request, str(exc))
        return redirect("cart:detail")
