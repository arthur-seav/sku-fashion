"""Storefront: write a review (UC-22) and see your own reviews."""

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import FormView, TemplateView

from core.permissions import CustomerRequiredMixin
from orders.models import OrderItem

from .forms import ReviewForm
from .services import ReviewError, ReviewService


class ReviewWriteView(CustomerRequiredMixin, FormView):
    template_name = "reviews/review_form.html"
    form_class = ReviewForm

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_customer:
            return super().dispatch(request, *args, **kwargs)  # login redirect / 403 from the mixin
        self.item = get_object_or_404(OrderItem.objects.select_related("order", "variant__product"),
                                      pk=kwargs["item_id"], order__user=request.user)
        self.service = ReviewService(request.user)
        try:
            self.review = self.service.check_eligible(self.item)
        except ReviewError as exc:
            messages.error(request, str(exc))
            return redirect("orders:order_detail", order_no=self.item.order.order_no)
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        if self.review:
            return {"rating": self.review.rating, "comment": self.review.comment}
        return {}

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["item"], ctx["review"] = self.item, self.review
        return ctx

    def form_valid(self, form):
        try:
            self.service.submit(self.item, form.cleaned_data["rating"], form.cleaned_data["comment"])
        except ReviewError as exc:
            form.add_error(None, str(exc))
            return self.form_invalid(form)
        messages.success(self.request, "Thank you! Your review will appear on the product page once our team "
                                       "has checked it.")
        return redirect("reviews:my_reviews")


class MyReviewsView(CustomerRequiredMixin, TemplateView):
    template_name = "reviews/my_reviews.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        service = ReviewService(self.request.user)
        ctx["to_review"] = service.items_to_review()
        ctx["reviews"] = service.my_reviews()
        return ctx
