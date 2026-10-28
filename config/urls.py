from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Storefront
    path("", include("core.urls")),
    path("shop/", include("catalog.urls")),
    path("cart/", include("cart.urls")),
    path("account/", include("accounts.urls")),
    # Back-office (Staff / Admin)
    path("backoffice/", include("reporting.urls")),
    path("backoffice/accounts/", include("accounts.backoffice_urls")),
    path("backoffice/catalog/", include("catalog.backoffice_urls")),
    path("backoffice/inventory/", include("inventory.backoffice_urls")),
    path("backoffice/promotions/", include("promotions.backoffice_urls")),
    path("backoffice/shipping/", include("shipping.backoffice_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
