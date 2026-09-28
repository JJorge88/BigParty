from django.contrib import admin

from .models import InventoryMovement


@admin.register(InventoryMovement)
class InventoryMovementAdmin(admin.ModelAdmin):
    list_display = ("created_at", "product", "movement_type", "quantity_delta", "stock_before", "stock_after", "user")
    list_filter = ("product", "movement_type", "created_at")
    search_fields = ("product__name", "reason", "user__username", "user__first_name", "user__last_name")
    list_select_related = ("product", "user")
    readonly_fields = ("product", "movement_type", "quantity_delta", "stock_before", "stock_after", "reason", "user", "created_at", "metadata")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return super().has_view_permission(request, obj) and request.user.has_perm("inventory.view_inventory")
