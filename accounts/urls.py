from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.LoginView.as_view(), name="login"),
    path("logout/", views.LogoutView.as_view(), name="logout"),
    path("register/", views.RegisterView.as_view(), name="register"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("password/reset/<uidb64>/<token>/", views.PasswordResetConfirmView.as_view(),
         name="password_reset_confirm"),
    path("addresses/", views.AddressListView.as_view(), name="address_list"),
    path("addresses/new/", views.AddressCreateView.as_view(), name="address_create"),
    path("addresses/<int:pk>/edit/", views.AddressUpdateView.as_view(), name="address_update"),
    path("addresses/<int:pk>/delete/", views.AddressDeleteView.as_view(), name="address_delete"),
    path("addresses/<int:pk>/default/", views.AddressMakeDefaultView.as_view(), name="address_default"),
]
