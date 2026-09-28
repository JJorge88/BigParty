from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.decorators import method_decorator
from django.views.decorators.debug import sensitive_post_parameters

from .forms import AdminUserChangeForm, AdminUserCreationForm
from .models import User


@admin.register(User)
class BigPartyUserAdmin(UserAdmin):
    form = AdminUserChangeForm
    add_form = AdminUserCreationForm
    list_display = ("username", "first_name", "last_name", "role", "is_active", "is_staff")
    list_filter = ("role", "is_active", "is_staff", "is_superuser")
    search_fields = ("username", "first_name", "last_name", "email")
    fieldsets = UserAdmin.fieldsets + (
        ("BIG PARTY", {"fields": ("role",)}),
        ("Cambiar PIN", {"fields": ("new_pin", "confirm_pin")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (("BIG PARTY", {"fields": ("role",)}),)

    @method_decorator(sensitive_post_parameters("new_pin", "confirm_pin"))
    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        return super().changeform_view(request, object_id, form_url, extra_context)
