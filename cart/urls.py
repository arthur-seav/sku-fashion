from django.urls import path

from . import views

app_name = "cart"

urlpatterns = [
    path("", views.CartDetailView.as_view(), name="detail"),
    path("add/", views.AddToCartView.as_view(), name="add"),
    path("items/<int:item_id>/update/", views.UpdateCartItemView.as_view(), name="update"),
    path("items/<int:item_id>/remove/", views.RemoveCartItemView.as_view(), name="remove"),
]
