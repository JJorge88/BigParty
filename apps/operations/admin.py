from django.contrib import admin
from django.db import transaction

from apps.audit.models import AuditLog
from apps.orders.admin import OperationalReadOnlyAdmin
from .models import OperationalDevice, PinAttempt, OperationalSession


@admin.register(OperationalDevice)
class OperationalDeviceAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "area", "is_active")
    list_filter = ("area", "is_active")
    readonly_fields = ("created_at", "updated_at")

    def has_add_permission(self, request):
        return super().has_add_permission(request) and request.user.has_perm("operations.configure_operational_device")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and request.user.has_perm("operations.configure_operational_device")

    def has_delete_permission(self, request, obj=None):
        return False

    @transaction.atomic
    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(user=request.user, action="operations.device_configured", entity="operations.operationaldevice", entity_id=str(obj.pk), data={"fields": form.changed_data})


@admin.register(OperationalSession)
class OperationalSessionAdmin(OperationalReadOnlyAdmin):
    exclude = ("token_hash", "binding_hash", "auth_hash")
    list_display = ("device", "user", "area", "created_at", "last_activity_at", "revoked_at")

    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields if f.name not in self.exclude)


admin.site.register(PinAttempt, OperationalReadOnlyAdmin)
