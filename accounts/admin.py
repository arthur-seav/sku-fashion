from django.contrib import admin

from .models import Address, User


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ["email", "first_name", "last_name", "role", "is_active", "locked_until"]
    list_filter = ["role", "is_active"]
    search_fields = ["email", "first_name", "last_name"]
    exclude = ["password"]
    readonly_fields = ["last_login", "date_joined"]
    inlines = [AddressInline]
