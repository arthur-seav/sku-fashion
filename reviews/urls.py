from django.urls import path

from . import views

app_name = "reviews"

urlpatterns = [
    path("", views.MyReviewsView.as_view(), name="my_reviews"),
    path("write/<int:item_id>/", views.ReviewWriteView.as_view(), name="write"),
]
