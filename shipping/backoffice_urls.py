from . import backoffice as bo

app_name = "shipping_bo"

urlpatterns = [
    *bo.ShippingMethodViewSet().urls(),
    *bo.ShippingRateViewSet().urls(),
]
