from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("django-admin/", admin.site.urls),
    # Storefront
    path("", include("core.urls")),
    path("account/", include("accounts.urls")),
    # Back-office (Staff / Admin)
    path("backoffice/", include("reporting.urls")),
    path("backoffice/accounts/", include("accounts.backoffice_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
