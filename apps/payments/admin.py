from django.contrib import admin

from apps.orders.admin import OperationalReadOnlyAdmin
from .models import Payment, PaymentAllocation, OrderAdjustment, AdjustmentAllocation, PaymentRefund, RefundAllocation


@admin.register(Payment)
class PaymentAdmin(OperationalReadOnlyAdmin):
    list_display = ("id", "order", "subaccount", "method", "amount", "status", "recorded_by", "cash_handoff_status", "created_at")
    list_filter = ("method", "status", "cash_handoff_status")
    list_select_related = ("order", "subaccount", "recorded_by")
    search_fields = ("=id", "=order__id", "reference")


@admin.register(OrderAdjustment)
class OrderAdjustmentAdmin(OperationalReadOnlyAdmin):
    list_display = ("id", "order", "subaccount", "adjustment_type", "amount", "reason", "authorized_by", "created_at")
    list_filter = ("adjustment_type",)
    list_select_related = ("order", "subaccount", "authorized_by")


@admin.register(PaymentRefund)
class PaymentRefundAdmin(OperationalReadOnlyAdmin):
    list_display = ("id", "payment", "amount", "reason", "return_to_inventory", "created_by", "created_at")
    list_select_related = ("payment", "created_by")


for model in (PaymentAllocation, AdjustmentAllocation, RefundAllocation):
    admin.site.register(model, OperationalReadOnlyAdmin)
