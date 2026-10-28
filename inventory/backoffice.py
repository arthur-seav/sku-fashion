"""Back-office stock screens (UC-14 Adjust Stock)."""

from datetime import timedelta

from django.contrib import messages
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import FormView, ListView

from catalog.models import ProductVariant
from core.permissions import StaffRequiredMixin

from .forms import REASON_SUGGESTIONS, StockAdjustmentForm
from .models import StockMovement
from .services import InsufficientStock, InventoryService


class StockListView(StaffRequiredMixin, ListView):
    template_name = "inventory/stock_list.html"
    context_object_name = "variants"
    paginate_by = 30

    def get_queryset(self):
        qs = ProductVariant.objects.select_related("product", "color", "size").filter(product__is_active=True)
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(Q(sku__icontains=q) | Q(product__name__icontains=q))
        status = self.request.GET.get("status", "")
        if status == "low":
            qs = qs.filter(stock_qty__lt=F("safety_level"), stock_qty__gt=0, is_active=True)
        elif status == "sold_out":
            qs = qs.filter(stock_qty=0, is_active=True)
        elif status == "alert":
            qs = qs.filter(stock_qty__lt=F("safety_level"), is_active=True)
        return qs.order_by("product__name", "color__sort_order", "size__sort_order")


class AdjustStockView(StaffRequiredMixin, FormView):
    template_name = "inventory/adjust.html"
    form_class = StockAdjustmentForm

    def dispatch(self, request, *args, **kwargs):
        self.variant = get_object_or_404(ProductVariant.objects.select_related("product", "color", "size"),
                                         pk=kwargs["pk"])
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["variant"] = self.variant
        ctx["movements"] = self.variant.movements.select_related("user")[:10]
        ctx["reason_suggestions"] = REASON_SUGGESTIONS
        return ctx

    def form_valid(self, form):
        try:
            movement = InventoryService(self.request.user).adjust(
                self.variant, form.signed_change, form.cleaned_data["reason"])
        except InsufficientStock as exc:
            form.add_error("quantity", f"Cannot remove {exc.requested}: only {exc.available} in stock.")
            return self.form_invalid(form)
        messages.success(self.request, f"{self.variant.sku}: stock is now {movement.balance_after}.")
        if self.variant.is_low_stock:  # FR-X12
            messages.warning(self.request, f"{self.variant.sku} is below its safety level "
                                           f"({movement.balance_after} < {self.variant.safety_level}).")
        next_url = self.request.POST.get("next")
        if next_url and next_url.startswith("/backoffice/"):
            return redirect(next_url)
        return redirect("inventory_bo:adjust", pk=self.variant.pk)


class MovementListView(StaffRequiredMixin, ListView):
    template_name = "inventory/movement_list.html"
    context_object_name = "movements"
    paginate_by = 30

    def get_queryset(self):
        qs = StockMovement.objects.select_related("variant__product", "variant__color", "variant__size", "user")
        params = self.request.GET
        if q := params.get("q", "").strip():
            qs = qs.filter(Q(variant__sku__icontains=q) | Q(variant__product__name__icontains=q)
                           | Q(reference__icontains=q) | Q(reason__icontains=q))
        if params.get("type") in StockMovement.Type.values:
            qs = qs.filter(type=params["type"])
        if start := parse_date(params.get("start", "") or ""):
            qs = qs.filter(created_at__date__gte=start)
        if end := parse_date(params.get("end", "") or ""):
            qs = qs.filter(created_at__date__lt=end + timedelta(days=1))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["today"] = timezone.localdate()
        return ctx
