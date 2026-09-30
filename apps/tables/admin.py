from apps.sync.services import sync_atomic, track
from apps.sync.admin import SyncAdminMixin
from django.contrib import admin

from .models import VenueTable
from .services import CONFIGURATION_FIELDS, update_table_configuration


@admin.register(VenueTable)
class VenueTableAdmin(SyncAdminMixin, admin.ModelAdmin):
    list_display = ("name", "area", "zone", "capacity", "operational_status", "reservable_web", "is_active")
    list_filter = ("area", "zone", "operational_status", "reservable_web", "is_active")
    search_fields = ("name", "area__name", "zone__name")
    list_select_related = ("area", "zone")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Información", {"fields": ("name", "capacity")}),
        ("Ubicación", {"fields": ("area", "zone")}),
        ("Reservas", {"fields": ("reservable_web",)}),
        ("Distribución visual", {
            "fields": ("sort_order", "layout_x", "layout_y", "layout_width", "layout_height", "layout_shape"),
            "description": "Porcentajes del área (0–100), desde la esquina superior izquierda. "
                           "Ancho y alto mayores que cero; la mesa debe quedar dentro del área.",
        }),
        ("Estado", {"fields": ("is_active", "operational_status", "created_at", "updated_at")}),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    @sync_atomic('local')
    def save_model(self, request, obj, form, change):
        track(obj)
        if change:
            changes = {
                field: form.cleaned_data[field]
                for field in form.changed_data if field in CONFIGURATION_FIELDS
            }
            update_table_configuration(obj, actor=request.user, **changes)
            obj.refresh_from_db()
        else:
            super().save_model(request, obj, form, change)
