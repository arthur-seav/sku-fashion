from . import backoffice as bo

app_name = "promotions_bo"

urlpatterns = [
    *bo.CouponViewSet().urls(),
    *bo.CampaignViewSet().urls(),
]
