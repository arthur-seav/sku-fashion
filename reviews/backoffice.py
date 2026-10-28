"""Back-office review moderation (FR-S12, UC-23)."""

from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views import View
from django.views.generic import ListView

from core.permissions import StaffRequiredMixin

from .forms import RejectForm
from .models import Review, ReviewStatus
from .services import RATING_LABELS, ReviewError, ReviewModerationService


class ReviewListView(StaffRequiredMixin, ListView):
    """The moderation queue. Opens on Pending; oldest first there, so the
    review that has waited longest is at the top."""

    template_name = "reviews/backoffice/review_list.html"
    context_object_name = "reviews"
    paginate_by = 20

    def status(self):
        value = self.request.GET.get("status", ReviewStatus.PENDING)
        return value if value in ReviewStatus.values or value == "all" else ReviewStatus.PENDING

    def get_queryset(self):
        qs = Review.objects.select_related("order_item__order__user", "order_item__variant__product",
                                           "moderated_by")
        status = self.status()
        if status != "all":
            qs = qs.filter(status=status)
        p = self.request.GET
        if p.get("rating", "").isdigit() and int(p["rating"]) in RATING_LABELS:
            qs = qs.filter(rating=int(p["rating"]))
        if q := p.get("q", "").strip():
            qs = qs.filter(Q(order_item__product_name__icontains=q) | Q(comment__icontains=q)
                           | Q(order_item__order__order_no__icontains=q)
                           | Q(order_item__order__user__email__icontains=q)
                           | Q(order_item__order__user__first_name__icontains=q)
                           | Q(order_item__order__user__last_name__icontains=q))
        return qs.order_by("submitted_at" if status == ReviewStatus.PENDING else "-submitted_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        counts = dict(Review.objects.values_list("status").annotate(n=Count("id")))
        ctx["status_tabs"] = [(s.value, s.label, counts.get(s.value, 0)) for s in ReviewStatus]
        ctx["total_count"] = sum(counts.values())
        ctx["current_status"] = self.status()
        ctx["ratings"] = list(range(5, 0, -1))
        ctx["reject_form"] = RejectForm()
        return ctx


class ReviewModerateView(StaffRequiredMixin, View):
    def post(self, request, pk, action):
        review = get_object_or_404(Review, pk=pk)
        service = ReviewModerationService(request.user)
        try:
            if action == "approve":
                service.approve(review)
                messages.success(request, f"Review of {review.order_item.product_name} published.")
            elif action == "reject":
                form = RejectForm(request.POST)
                service.reject(review, form.data.get("note", ""))
                messages.success(request, f"Review of {review.order_item.product_name} rejected; "
                                          "the customer can see the reason and edit it.")
            else:
                messages.error(request, "Unknown action.")
        except ReviewError as exc:
            messages.error(request, str(exc))
        target = request.POST.get("next", "")
        if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()},
                                           require_https=request.is_secure()):
            return redirect(target)
        return redirect("reviews_bo:review_list")
