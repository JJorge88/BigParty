from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "action", "entity", "entity_id")
    list_filter = ("action", "entity", "created_at")
    search_fields = ("action", "entity", "entity_id", "user__username")
    readonly_fields = ("user", "action", "entity", "entity_id", "data", "created_at")
    list_select_related = ("user",)
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
