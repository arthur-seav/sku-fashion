from django.urls import path

from . import backoffice as bo

app_name = "inventory_bo"

urlpatterns = [
    path("", bo.StockListView.as_view(), name="stock_list"),
    path("variants/<int:pk>/adjust/", bo.AdjustStockView.as_view(), name="adjust"),
    path("movements/", bo.MovementListView.as_view(), name="movement_list"),
]
