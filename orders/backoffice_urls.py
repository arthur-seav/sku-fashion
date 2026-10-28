from django.urls import path

from . import backoffice as bo

app_name = "orders_bo"

urlpatterns = [
    path("", bo.OrderListView.as_view(), name="order_list"),
    path("<str:order_no>/", bo.OrderDetailView.as_view(), name="order_detail"),
    path("<str:order_no>/<slug:action>/", bo.OrderActionView.as_view(), name="order_action"),
]
