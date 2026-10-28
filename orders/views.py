"""Customer-facing order views: checkout (UC-07) and order history (UC-09)."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import DetailView, ListView

from cart.services import CartService
from core.permissions import CustomerRequiredMixin
from inventory.services import InsufficientStock
from payments.providers import BankTransferProvider, registry
from promotions.services import CouponError
from shipping.models import ShippingMethod

from .forms import CheckoutForm
from .models import Order
from .services import CheckoutError, CheckoutService


class CheckoutView(CustomerRequiredMixin, View):
    template_name = "orders/checkout.html"
    SESSION_PRICES = "checkout_prices"

    def service(self):
        return CheckoutService(self.request.user, CartService(self.request))

    def get(self, request):
        service = self.service()
        summary = service.cart.summary()
        try:
            service.validate_cart(summary)
        except CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect("cart:detail")
        default_address = request.user.addresses.filter(is_default=True).first()
        method = ShippingMethod.objects.filter(is_active=True).first()
        initial = {**CheckoutForm.initial_from_address(default_address),
                   "shipping_method": method, "payment_method": registry.all()[0].code}
        form = CheckoutForm(initial=initial)
        return self._render(service, form, summary, method, initial.get("province", ""), None)

    def post(self, request):
        service = self.service()
        summary = service.cart.summary()
        try:
            service.validate_cart(summary)
        except CheckoutError as exc:
            messages.error(request, str(exc))
            return redirect("cart:detail")

        form = CheckoutForm(request.POST)
        form_ok = form.is_valid()
        method = ShippingMethod.objects.filter(pk=request.POST.get("shipping_method"), is_active=True).first()
        province = request.POST.get("province", "")

        coupon, code = None, request.POST.get("coupon_code", "").strip()
        if code:
            try:
                coupon = service.apply_coupon(code, summary)  # FR-C04: discount shown immediately
            except CouponError as exc:
                form.add_error("coupon_code", str(exc))
                form_ok = False

        if request.POST.get("action") != "place" or not form_ok:
            return self._render(service, form, summary, method, province, coupon)

        try:
            order = service.place_order(
                address=form.address,
                shipping_method=form.cleaned_data["shipping_method"],
                provider_code=form.cleaned_data["payment_method"],
                coupon_code=code,
                shown_prices=request.session.get(self.SESSION_PRICES),
            )
        except (CheckoutError, InsufficientStock) as exc:
            # UC-07 1a / 9a: nothing was saved; back to the cart with the reason.
            messages.error(request, str(exc))
            return redirect("cart:detail")
        request.session.pop(self.SESSION_PRICES, None)
        messages.success(request, f"Thank you! Order {order.order_no} has been placed.")
        return redirect(f"{reverse('orders:order_detail', args=[order.order_no])}?placed=1")

    def _render(self, service, form, summary, method, province, coupon):
        totals = service.quote(summary, method, province, coupon)
        # Remember the prices shown, so a change before confirmation is caught (UC-07 1a).
        self.request.session[self.SESSION_PRICES] = service.snapshot(summary)
        return render(self.request, self.template_name, {
            "form": form,
            "summary": summary,
            "totals": totals,
            "coupon": coupon,
            "tax_rate": service.tax_rate,
            "addresses": self.request.user.addresses.all(),
            "providers": registry.all(),
            "bank": BankTransferProvider.bank_details(),
        })


class CustomerOrderMixin(CustomerRequiredMixin):
    def get_queryset(self):
        return Order.objects.filter(user=self.request.user)


class OrderListView(CustomerOrderMixin, ListView):
    template_name = "orders/order_list.html"
    context_object_name = "orders"
    paginate_by = 10

    def get_queryset(self):
        return super().get_queryset().prefetch_related("payments", "items")


class OrderDetailView(CustomerOrderMixin, DetailView):
    template_name = "orders/order_detail.html"
    context_object_name = "order"
    slug_field = "order_no"
    slug_url_kwarg = "order_no"

    def get_queryset(self):
        return super().get_queryset().select_related("shipping_method").prefetch_related(
            "items", "payments", "history")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        payment = order.payment
        ctx["payment"] = payment
        ctx["provider"] = registry.get(payment.provider) if payment else None
        ctx["instructions"] = ctx["provider"].instructions(payment) if payment else ""
        ctx["just_placed"] = self.request.GET.get("placed") == "1"
        ctx["coupon_redemption"] = getattr(order, "coupon_redemption", None)
        return ctx
