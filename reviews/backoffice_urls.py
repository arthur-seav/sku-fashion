from django.urls import path

from . import backoffice as bo

app_name = "reviews_bo"

urlpatterns = [
    path("", bo.ReviewListView.as_view(), name="review_list"),
    path("<int:pk>/<slug:action>/", bo.ReviewModerateView.as_view(), name="review_moderate"),
]
