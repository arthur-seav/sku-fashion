from django.urls import path

from . import views

app_name = "orders"

urlpatterns = [
    path("checkout/", views.CheckoutView.as_view(), name="checkout"),
    path("", views.OrderListView.as_view(), name="order_list"),
    path("<str:order_no>/", views.OrderDetailView.as_view(), name="order_detail"),
    path("<str:order_no>/cancel/", views.CancelOrderView.as_view(), name="order_cancel"),
    path("<str:order_no>/receipt/", views.UploadReceiptView.as_view(), name="upload_receipt"),
]
