from decimal import Decimal

from django.conf import settings
from django.db import models


def money_field(label="monto (Q)"):
    return models.DecimalField(label, max_digits=14, decimal_places=2)


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "CASH", "Efectivo"
        CARD = "CARD", "Tarjeta"
        TRANSFER = "TRANSFER", "Transferencia"
        DEPOSIT = "DEPOSIT", "Depósito"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        CONFIRMED = "CONFIRMED", "Confirmado"
        REJECTED = "REJECTED", "Rechazado"
        REFUNDED = "REFUNDED", "Reembolsado"

    class CashHandoffStatus(models.TextChoices):
        NOT_REQUIRED = "NOT_REQUIRED", "No requerida"
        PENDING = "PENDING", "Pendiente"
        DELIVERED = "DELIVERED", "Entregada"

    order = models.ForeignKey("orders.TableOrder", on_delete=models.PROTECT, related_name="payments")
    subaccount = models.ForeignKey("orders.SubAccount", on_delete=models.PROTECT, null=True, blank=True, related_name="payments")
    method = models.CharField("método", max_length=8, choices=Method.choices)
    status = models.CharField("estado", max_length=9, choices=Status.choices)
    amount = money_field()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_payments")
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="confirmed_payments")
    reference = models.CharField("referencia", max_length=200, blank=True)
    notes = models.TextField("notas", blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    cash_handoff_status = models.CharField("entrega de efectivo", max_length=12, choices=CashHandoffStatus.choices, default=CashHandoffStatus.NOT_REQUIRED)

    class Meta:
        ordering = ("created_at", "pk")
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"
        permissions = [
            ("record_payment", "Puede registrar pagos"),
            ("verify_transfer_payment", "Puede verificar transferencias y depósitos"),
            ("reject_transfer_payment", "Puede rechazar transferencias y depósitos"),
            ("apply_order_adjustment", "Puede autorizar descuentos y cortesías"),
            ("refund_payment", "Puede reembolsar pagos"),
            ("close_order", "Puede cerrar cuentas liquidadas"),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_amount_positive"),
            models.CheckConstraint(condition=models.Q(method__in=["CASH", "CARD", "TRANSFER", "DEPOSIT"]), name="payments_method_valid"),
            models.CheckConstraint(condition=models.Q(status__in=["PENDING", "CONFIRMED", "REJECTED", "REFUNDED"]), name="payments_status_valid"),
            models.CheckConstraint(condition=~models.Q(method__in=["TRANSFER", "DEPOSIT"]) | ~models.Q(reference=""), name="payments_reference_required"),
            models.CheckConstraint(condition=models.Q(method__in=["TRANSFER", "DEPOSIT"]) | models.Q(status__in=["CONFIRMED", "REFUNDED"]), name="payments_immediate_confirmed"),
            models.CheckConstraint(condition=(models.Q(status__in=["CONFIRMED", "REFUNDED"], confirmed_at__isnull=False, confirmed_by__isnull=False) | models.Q(status__in=["PENDING", "REJECTED"], confirmed_at__isnull=True, confirmed_by__isnull=True)), name="payments_confirmation_consistent"),
            models.CheckConstraint(condition=models.Q(cash_handoff_status__in=["NOT_REQUIRED", "PENDING", "DELIVERED"]), name="payments_handoff_valid"),
            models.CheckConstraint(condition=models.Q(method="CASH") | models.Q(cash_handoff_status="NOT_REQUIRED"), name="payments_handoff_cash_only"),
        ]

    @property
    def change_due(self):
        if self.method != "CASH":
            return Decimal("0.00")
        return Decimal(self.metadata.get("received_amount", str(self.amount))) - self.amount

    def __str__(self):
        return f"Pago #{self.pk} · {self.get_method_display()} · Q{self.amount}"


class UnitAllocation(models.Model):
    """Una fila por unidad física; los pagos por monto pueden cubrir solo parte de ella."""
    order_line = models.ForeignKey("orders.OrderLine", on_delete=models.PROTECT, related_name="%(class)s_set")
    unit_number = models.PositiveIntegerField("unidad dentro de la línea")
    quantity = models.PositiveIntegerField("unidad completa seleccionada", null=True, blank=True)
    amount = money_field()

    class Meta:
        abstract = True
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0, unit_number__gt=0), name="%(app_label)s_%(class)s_positive"),
            models.CheckConstraint(condition=models.Q(quantity__isnull=True) | models.Q(quantity=1), name="%(app_label)s_%(class)s_quantity"),
        ]


class PaymentAllocation(UnitAllocation):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="allocations")

    class Meta(UnitAllocation.Meta):
        abstract = False
        constraints = UnitAllocation.Meta.constraints + [
            models.UniqueConstraint(fields=("payment", "order_line", "unit_number"), name="payments_allocation_unit_unique"),
        ]
        verbose_name = "Asignación de pago"
        verbose_name_plural = "Asignaciones de pago"


class OrderAdjustment(models.Model):
    class Kind(models.TextChoices):
        DISCOUNT = "DISCOUNT", "Descuento"
        COURTESY = "COURTESY", "Cortesía"

    order = models.ForeignKey("orders.TableOrder", on_delete=models.PROTECT, related_name="adjustments")
    subaccount = models.ForeignKey("orders.SubAccount", on_delete=models.PROTECT, null=True, blank=True, related_name="adjustments")
    adjustment_type = models.CharField("tipo", max_length=8, choices=Kind.choices)
    amount = money_field()
    reason = models.TextField("motivo")
    authorized_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Descuento o cortesía"
        verbose_name_plural = "Descuentos y cortesías"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_adjustment_positive"),
            models.CheckConstraint(condition=~models.Q(reason=""), name="payments_adjustment_reason"),
            models.CheckConstraint(condition=models.Q(adjustment_type__in=["DISCOUNT", "COURTESY"]), name="payments_adjustment_type_valid"),
        ]


class AdjustmentAllocation(UnitAllocation):
    adjustment = models.ForeignKey(OrderAdjustment, on_delete=models.PROTECT, related_name="allocations")

    class Meta(UnitAllocation.Meta):
        abstract = False
        constraints = UnitAllocation.Meta.constraints + [
            models.UniqueConstraint(fields=("adjustment", "order_line", "unit_number"), name="payments_adjustment_unit_unique"),
        ]


class PaymentRefund(models.Model):
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name="refunds")
    amount = money_field()
    reason = models.TextField("motivo")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    return_to_inventory = models.BooleanField("reintegrar inventario", default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reembolso"
        verbose_name_plural = "Reembolsos"
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_refund_positive"),
            models.CheckConstraint(condition=~models.Q(reason=""), name="payments_refund_reason"),
        ]


class RefundAllocation(models.Model):
    refund = models.ForeignKey(PaymentRefund, on_delete=models.PROTECT, related_name="allocations")
    payment_allocation = models.ForeignKey(PaymentAllocation, on_delete=models.PROTECT, related_name="refund_allocations")
    amount = money_field()
    quantity = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=("refund", "payment_allocation"), name="payments_refund_allocation_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payments_refund_allocation_positive"),
            models.CheckConstraint(condition=models.Q(quantity__isnull=True) | models.Q(quantity=1), name="payments_refund_allocation_quantity"),
        ]
