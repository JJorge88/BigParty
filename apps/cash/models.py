import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone


def money(label, **kwargs):
    return models.DecimalField(label, max_digits=14, decimal_places=2, **kwargs)


class BusinessDay(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        CLOSED = "CLOSED", "Cerrada"

    business_date = models.DateField("fecha comercial", unique=True)
    status = models.CharField("estado", max_length=6, choices=Status.choices, default=Status.OPEN)
    opened_at = models.DateTimeField(default=timezone.now)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_business_days")
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="closed_business_days", null=True, blank=True)
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reopened_business_days", null=True, blank=True)
    reopen_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Jornada"
        verbose_name_plural = "Jornadas"
        ordering = ("-business_date", "-pk")
        permissions = [("open_business_day", "Puede abrir jornadas"), ("close_business_day", "Puede cerrar jornadas"), ("reopen_business_day", "Puede reabrir jornadas")]
        constraints = [
            models.UniqueConstraint(fields=("status",), condition=models.Q(status="OPEN"), name="cash_one_open_day"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "CLOSED"]), name="cash_day_status_valid"),
            models.CheckConstraint(condition=models.Q(status="OPEN", closed_at__isnull=True, closed_by__isnull=True) | models.Q(status="CLOSED", closed_at__isnull=False, closed_by__isnull=False), name="cash_day_close_consistent"),
        ]

    def __str__(self):
        return f"Jornada {self.business_date} · {self.get_status_display()}"


class BusinessDayReopen(models.Model):
    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, related_name="reopens")
    reopened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reopened_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField("motivo")
    previous_closed_at = models.DateTimeField()
    previous_closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reopened_day_previous_closures")

    class Meta:
        constraints = [models.CheckConstraint(condition=~models.Q(reason=""), name="cash_reopen_reason_required")]
        ordering = ("reopened_at", "pk")


class CashRegister(models.Model):
    binding_version = models.UUIDField(default=uuid.uuid4, editable=False)
    name = models.CharField("nombre", max_length=100)
    code = models.SlugField("código", max_length=30, unique=True)
    area = models.ForeignKey("venues.Area", on_delete=models.PROTECT, related_name="cash_registers")
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Estación de caja"
        verbose_name_plural = "Estaciones de caja"
        ordering = ("code",)
        permissions = [("configure_cash_register_device", "Puede configurar navegadores de caja")]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.pk:
            previous = type(self).objects.get(pk=self.pk)
            if self.sessions.exists() and (previous.area_id != self.area_id or previous.code != self.code):
                raise ValidationError("No se puede cambiar el código o área de una caja con historial.")
            if not self.is_active and self.sessions.filter(status="OPEN").exists():
                raise ValidationError("Cierra la sesión antes de desactivar la caja.")

    @transaction.atomic
    def save(self, *args, **kwargs):
        from .guards import lock_operation_gate
        lock_operation_gate()
        changed = False
        if self.pk:
            previous = type(self).objects.select_for_update().get(pk=self.pk)
            changed = any(getattr(previous, key) != getattr(self, key) for key in ("area_id", "code", "is_active"))
            if changed:
                self.binding_version = uuid.uuid4()
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"binding_version"}
        self.full_clean()
        result = super().save(*args, **kwargs)
        if changed:
            self.cash_access_sessions.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        return result


class CashSession(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Abierta"
        CLOSED = "CLOSED", "Cerrada"

    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, related_name="cash_sessions")
    register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="sessions")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_sessions")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="opened_cash_sessions")
    status = models.CharField(max_length=6, choices=Status.choices, default=Status.OPEN)
    opening_float = money("fondo inicial")
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    counted_cash = money("efectivo contado", null=True, blank=True)
    counted_at = models.DateTimeField(null=True, blank=True)
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_counts", null=True, blank=True)
    expected_cash_at_close = money("efectivo esperado al contar", null=True, blank=True)
    difference = money("diferencia", null=True, blank=True)
    closing_reason = models.TextField("motivo de diferencia", blank=True)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="closed_cash_sessions", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Sesión de caja"
        verbose_name_plural = "Sesiones de caja"
        ordering = ("-opened_at", "-pk")
        permissions = [("open_cash_session", "Puede abrir sesiones de caja"), ("receive_waiter_cash", "Puede recibir efectivo de meseros"), ("approve_cash_withdrawal", "Puede aprobar retiros"), ("close_cash_session", "Puede contar y cerrar caja"), ("view_cash_session_financials", "Puede consultar información financiera de caja"), ("record_cash_refund", "Puede registrar salidas físicas por reembolso")]
        constraints = [
            models.UniqueConstraint(fields=("register",), condition=models.Q(status="OPEN"), name="cash_one_open_session_per_register"),
            models.CheckConstraint(condition=models.Q(status__in=["OPEN", "CLOSED"]), name="cash_session_status_valid"),
            models.CheckConstraint(condition=models.Q(opening_float__gte=0), name="cash_float_nonnegative"),
            models.CheckConstraint(condition=models.Q(counted_cash__isnull=True) | models.Q(counted_cash__gte=0), name="cash_count_nonnegative"),
            models.CheckConstraint(condition=(models.Q(counted_cash__isnull=True, counted_at__isnull=True, counted_by__isnull=True, expected_cash_at_close__isnull=True, difference__isnull=True) | models.Q(counted_cash__isnull=False, counted_at__isnull=False, counted_by__isnull=False, expected_cash_at_close__isnull=False, difference=models.F("counted_cash") - models.F("expected_cash_at_close"))), name="cash_count_snapshot_consistent"),
            models.CheckConstraint(condition=models.Q(status="OPEN", closed_at__isnull=True, closed_by__isnull=True) | models.Q(status="CLOSED", closed_at__isnull=False, closed_by__isnull=False, counted_cash__isnull=False), name="cash_session_close_consistent"),
            models.CheckConstraint(condition=~models.Q(status="CLOSED") | models.Q(difference=0) | ~models.Q(closing_reason=""), name="cash_difference_reason_required"),
        ]

    def __str__(self):
        return f"{self.register} · sesión #{self.pk} · {self.cashier}"


class CashHandoff(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pendiente"
        DELIVERED = "DELIVERED", "Entregado"

    payment = models.OneToOneField("payments.Payment", on_delete=models.PROTECT, related_name="cash_handoff")
    waiter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_handoffs")
    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="handoffs", null=True, blank=True)
    amount = money("monto entregado")
    status = models.CharField(max_length=9, choices=Status.choices, default=Status.PENDING)
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="received_cash_handoffs", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    received_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Entrega de efectivo"
        verbose_name_plural = "Entregas de efectivo"
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="cash_handoff_positive"),
            models.CheckConstraint(condition=models.Q(status="PENDING", cash_session__isnull=True, received_at__isnull=True, received_by__isnull=True) | models.Q(status="DELIVERED", cash_session__isnull=False, received_at__isnull=False, received_by__isnull=False), name="cash_handoff_state_consistent"),
        ]

    def __str__(self):
        return f"Pago #{self.payment_id} · {self.waiter} · Q{self.amount}"


class CashMovement(models.Model):
    class MovementType(models.TextChoices):
        DIRECT_CASH_PAYMENT = "DIRECT_CASH_PAYMENT", "Cobro en efectivo"
        WAITER_HANDOFF = "WAITER_HANDOFF", "Entrega de mesero"
        WITHDRAWAL = "WITHDRAWAL", "Retiro de efectivo"
        CASH_REFUND = "CASH_REFUND", "Reembolso en efectivo"

    cash_session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    amount = money("monto")
    reason = models.TextField("motivo", blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cash_movements")
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="approved_cash_movements", null=True, blank=True)
    payment = models.ForeignKey("payments.Payment", on_delete=models.PROTECT, related_name="cash_movements", null=True, blank=True)
    handoff = models.OneToOneField(CashHandoff, on_delete=models.PROTECT, related_name="movement", null=True, blank=True)
    refund = models.OneToOneField("payments.PaymentRefund", on_delete=models.PROTECT, related_name="cash_movement", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = "Movimiento físico de efectivo"
        verbose_name_plural = "Movimientos físicos de efectivo"
        ordering = ("created_at", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="cash_movement_positive"),
            models.UniqueConstraint(fields=("payment",), condition=models.Q(movement_type__in=["DIRECT_CASH_PAYMENT", "WAITER_HANDOFF"]), name="cash_one_receipt_per_payment"),
            models.CheckConstraint(condition=(models.Q(movement_type="DIRECT_CASH_PAYMENT", payment__isnull=False, handoff__isnull=True, refund__isnull=True) | models.Q(movement_type="WAITER_HANDOFF", payment__isnull=False, handoff__isnull=False, refund__isnull=True) | (models.Q(movement_type="WITHDRAWAL", payment__isnull=True, handoff__isnull=True, refund__isnull=True, approved_by__isnull=False) & ~models.Q(reason="")) | (models.Q(movement_type="CASH_REFUND", payment__isnull=False, handoff__isnull=True, refund__isnull=False) & ~models.Q(reason=""))), name="cash_movement_origin_consistent"),
        ]
