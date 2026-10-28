from django.urls import path

from . import views

app_name = "accounts_bo"

urlpatterns = [
    path("", views.BackofficeAccountListView.as_view(), name="account_list"),
    path("new/", views.BackofficeAccountCreateView.as_view(), name="account_create"),
    path("<int:pk>/<slug:action>/", views.BackofficeAccountActionView.as_view(), name="account_action"),
]
