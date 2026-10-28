from django.urls import path

from . import backoffice as bo

app_name = "catalog_bo"

urlpatterns = [
    *bo.CategoryViewSet().urls(),
    *bo.BrandViewSet().urls(),
    *bo.MaterialViewSet().urls(),
    *bo.SizeViewSet().urls(),
    *bo.ColorViewSet().urls(),
    *bo.SizeChartViewSet().urls(),
    *bo.ProductViewSet().urls(),
    path("products/<int:pk>/", bo.ProductDetailView.as_view(), name="product_detail"),
    path("products/<int:pk>/images/", bo.ProductImageUploadView.as_view(), name="product_image_upload"),
    path("images/<int:pk>/<slug:action>/", bo.ProductImageActionView.as_view(), name="product_image_action"),
    path("products/<int:pk>/variants/generate/", bo.VariantGenerateView.as_view(), name="variant_generate"),
    path("variants/<int:pk>/edit/", bo.VariantUpdateView.as_view(), name="variant_update"),
    path("variants/<int:pk>/delete/", bo.VariantDeleteView.as_view(), name="variant_delete"),
]
