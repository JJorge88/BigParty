from django.contrib import admin

from apps.audit.models import AuditLog
from apps.orders.admin import OperationalReadOnlyAdmin
from .models import CashRegister, CashSession, CashHandoff, CashMovement, BusinessDay, BusinessDayReopen


@admin.register(CashRegister)
class CashRegisterAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "area", "is_active")
    list_filter = ("area", "is_active")
    readonly_fields = ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        AuditLog.objects.create(user=request.user, action="cash.register_changed" if change else "cash.register_created",
                                entity="cash.cashregister", entity_id=str(obj.pk), data={"fields": form.changed_data})


class FinancialReadOnlyAdmin(OperationalReadOnlyAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.has_perm("cash.view_cash_session_financials") and super().has_view_permission(request, obj)


@admin.register(CashSession)
class CashSessionAdmin(FinancialReadOnlyAdmin):
    list_display = ("id", "register", "cashier", "business_day", "status", "opened_at", "closed_at")
    list_filter = ("status", "register", "business_day")
    list_select_related = ("register", "cashier", "business_day")


@admin.register(CashMovement)
class CashMovementAdmin(FinancialReadOnlyAdmin):
    list_display = ("id", "cash_session", "movement_type", "amount", "created_by", "approved_by", "created_at")
    list_filter = ("movement_type", "cash_session__business_day")
    list_select_related = ("cash_session__register", "cash_session__cashier", "created_by", "approved_by")


@admin.register(CashHandoff)
class CashHandoffAdmin(FinancialReadOnlyAdmin):
    list_display = ("id", "payment", "waiter", "amount", "status", "cash_session", "received_by")
    list_filter = ("status",)
    list_select_related = ("payment", "waiter", "cash_session__register", "cash_session__cashier", "received_by")


admin.site.register(BusinessDay, OperationalReadOnlyAdmin)
admin.site.register(BusinessDayReopen, OperationalReadOnlyAdmin)
