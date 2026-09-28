from django.contrib import admin

from .models import (TableOrder, OrderTableLink, SubAccount, OrderLine, OrderLineModifier,
                     OrderLineComponent, PreparationTicket, PreparationTicketItem, OrderActivity)


class OperationalReadOnlyAdmin(admin.ModelAdmin):
    """Las escrituras operativas pasan exclusivamente por services."""
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(TableOrder)
class TableOrderAdmin(OperationalReadOnlyAdmin):
    list_display = ("order_number", "primary_table", "area", "responsible_waiter", "status", "billing_mode", "opened_at")
    list_filter = ("status", "billing_mode", "area")
    search_fields = ("=id", "primary_table__name", "responsible_waiter__username")
    list_select_related = ("primary_table", "area", "responsible_waiter")


@admin.register(OrderLine)
class OrderLineAdmin(OperationalReadOnlyAdmin):
    list_display = ("order", "product_name_snapshot", "subaccount", "quantity", "unit_price", "status", "created_by")
    list_filter = ("status",)
    search_fields = ("product_name_snapshot", "=order__id")
    list_select_related = ("order", "subaccount", "created_by")


@admin.register(PreparationTicket)
class PreparationTicketAdmin(OperationalReadOnlyAdmin):
    list_display = ("order", "sequence_number", "ticket_type", "table_name_snapshot", "created_at", "created_by")
    list_filter = ("ticket_type", "created_at")
    list_select_related = ("order", "created_by")


@admin.register(OrderActivity)
class OrderActivityAdmin(OperationalReadOnlyAdmin):
    list_display = ("order", "origin_order", "user", "activity_type", "created_at")
    list_filter = ("activity_type", "created_at")
    list_select_related = ("order", "origin_order", "user")


for model in (OrderTableLink, SubAccount, OrderLineModifier, OrderLineComponent, PreparationTicketItem):
    admin.site.register(model, OperationalReadOnlyAdmin)
