from django.urls import path

from . import views

app_name = "reporting"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("reports/sales/", views.SalesReportView.as_view(), name="sales"),
    path("reports/best-sellers/", views.BestSellerView.as_view(), name="best_sellers"),
    path("reports/stock/", views.StockReportView.as_view(), name="stock"),
]
