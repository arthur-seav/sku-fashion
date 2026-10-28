"""Back-office order processing (UC-15, UC-16, UC-17)."""

from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.utils.dateparse import parse_date
from django.views import View
from django.views.generic import DetailView, ListView

from core.forms import BootstrapFormMixin
from core.permissions import StaffRequiredMixin
from payments.models import Payment
from payments.services import PaymentError, PaymentService
from shipping.services import ShipmentError, ShipmentService

from .models import Order, OrderStatus
from .workflow import InvalidTransition, OrderWorkflow


class ShipmentForm(BootstrapFormMixin, forms.Form):
    carrier = forms.CharField(max_length=100, widget=forms.TextInput(attrs={"list": "carriers"}))
    tracking_no = forms.CharField(label="Tracking number", max_length=100)


class RefundForm(BootstrapFormMixin, forms.Form):
    amount = forms.DecimalField(max_digits=12, decimal_places=2, min_value=0.01)
    reason = forms.CharField(max_length=255)


class ReconcileForm(BootstrapFormMixin, forms.Form):
    transaction_ref = forms.CharField(label="Bank transaction reference", max_length=100, required=False)


class OrderListView(StaffRequiredMixin, ListView):
    template_name = "orders/backoffice/order_list.html"
    context_object_name = "orders"
    paginate_by = 25

    def get_queryset(self):
        qs = Order.objects.select_related("user").prefetch_related("payments").annotate(
            item_count=Count("items"))
        p = self.request.GET
        if p.get("status") in OrderStatus.values:
            qs = qs.filter(status=p["status"])
        if p.get("awaiting") == "1":
            qs = qs.filter(awaiting_action_q())
        if start := parse_date(p.get("start") or ""):
            qs = qs.filter(placed_at__date__gte=start)
        if end := parse_date(p.get("end") or ""):
            qs = qs.filter(placed_at__date__lt=end + timedelta(days=1))
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(order_no__icontains=q) | Q(user__email__icontains=q) | Q(user__first_name__icontains=q)
                           | Q(user__last_name__icontains=q) | Q(ship_recipient__icontains=q)
                           | Q(ship_phone__icontains=q))
        return qs.distinct().order_by("-placed_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = dict(Order.objects.values_list("status").annotate(n=Count("id")))
        ctx["status_tabs"] = [(s.value, s.label, counts.get(s.value, 0)) for s in OrderStatus]
        ctx["total_count"] = sum(counts.values())
        return ctx


def awaiting_action_q():
    """Orders a staff member must act on next (dashboard + sidebar badge)."""
    return (Q(status=OrderStatus.PAID) | Q(status=OrderStatus.PREPARING)
            | Q(status=OrderStatus.PENDING_PAYMENT, payments__status="PENDING",
                payments__receipt_image__isnull=False) & ~Q(payments__receipt_image=""))


def awaiting_action_count():
    return Order.objects.filter(awaiting_action_q()).distinct().count()


class OrderDetailView(StaffRequiredMixin, DetailView):
    template_name = "orders/backoffice/order_detail.html"
    slug_field = "order_no"
    slug_url_kwarg = "order_no"
    queryset = Order.objects.select_related("user", "shipping_method").prefetch_related(
        "items__campaign", "payments__refunds__user", "payments__verified_by", "history__user")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        order = self.object
        # Buttons for plain transitions; Paid / Shipped / Cancelled have their own forms.
        special = {OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.CANCELLED}
        ctx["next_statuses"] = [s for s in order.allowed_transitions() if s not in special]
        ctx["shipment"] = getattr(order, "shipment", None)
        ctx["shipment_form"] = ShipmentForm()
        ctx["refund_form"] = RefundForm()
        ctx["reconcile_form"] = ReconcileForm()
        ctx["redemption"] = getattr(order, "coupon_redemption", None)
        ctx["carriers"] = ["Grab Express", "J&T Express", "VET Express", "Virak Buntham", "In-house rider"]
        return ctx


class OrderActionView(StaffRequiredMixin, View):
    def post(self, request, order_no, action):
        order = get_object_or_404(Order, order_no=order_no)
        user = request.user
        try:
            if action == "transition":
                OrderWorkflow(order, user).transition(request.POST["to"], request.POST.get("note", ""))
                messages.success(request, f"{order.order_no} is now {OrderStatus(request.POST['to']).label}.")
            elif action == "cancel":
                OrderWorkflow(order, user).cancel(request.POST.get("note", "Cancelled by staff"))
                messages.success(request, f"{order.order_no} cancelled; stock restored.")
            elif action == "ship":
                form = ShipmentForm(request.POST)
                if not form.is_valid():
                    raise ShipmentError("Carrier and tracking number are both required.")
                ShipmentService(user).create(order, form.cleaned_data["carrier"], form.cleaned_data["tracking_no"])
                messages.success(request, f"Shipment created; {order.order_no} is now Shipped.")
            elif action == "delivered":
                ShipmentService(user).mark_delivered(order.shipment)
                messages.success(request, "Shipment marked as delivered.")
            elif action == "reconcile":
                payment = get_object_or_404(Payment, pk=request.POST["payment"], order=order)
                PaymentService(user).reconcile(payment, request.POST.get("transaction_ref", "").strip())
                messages.success(request, f"Payment reconciled; {order.order_no} is now Paid.")
            elif action == "refund":
                payment = get_object_or_404(Payment, pk=request.POST["payment"], order=order)
                form = RefundForm(request.POST)
                if not form.is_valid():
                    raise PaymentError("Enter a positive amount and a reason.")
                refund = PaymentService(user).refund(payment, form.cleaned_data["amount"], form.cleaned_data["reason"])
                messages.success(request, f"Refund of {refund.amount} recorded.")
        except (InvalidTransition, ShipmentError, PaymentError) as exc:
            messages.error(request, str(exc))
        return redirect("orders_bo:order_detail", order_no=order.order_no)
