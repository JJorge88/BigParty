import uuid

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone


class OperationalDevice(models.Model):
    class DeviceType(models.TextChoices):
        WAITER_TABLET = "WAITER_TABLET", "Tablet de meseros"

    name = models.CharField("nombre", max_length=100)
    code = models.SlugField("código", max_length=40, unique=True)
    device_type = models.CharField("tipo", max_length=20, choices=DeviceType.choices, default=DeviceType.WAITER_TABLET)
    area = models.ForeignKey("venues.Area", verbose_name="área asignada", on_delete=models.PROTECT)
    is_active = models.BooleanField("activo", default=True)
    binding_version = models.UUIDField(default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("name", "pk")
        verbose_name = "Dispositivo operativo"
        verbose_name_plural = "Dispositivos operativos"
        permissions = [("configure_operational_device", "Puede configurar dispositivos operativos")]
        constraints = [models.CheckConstraint(condition=models.Q(device_type="WAITER_TABLET"), name="operations_device_type_valid")]

    @transaction.atomic
    def save(self, *args, **kwargs):
        changed_binding = False
        if self.pk:
            previous = type(self).objects.select_for_update().get(pk=self.pk)
            changed_binding = any(getattr(previous, field) != getattr(self, field) for field in ("area_id", "is_active", "device_type", "code"))
            if changed_binding:
                self.binding_version = uuid.uuid4()
                if kwargs.get("update_fields") is not None:
                    kwargs["update_fields"] = set(kwargs["update_fields"]) | {"binding_version"}
        self.full_clean()
        result = super().save(*args, **kwargs)
        if changed_binding:
            self.operational_sessions.filter(revoked_at__isnull=True).update(revoked_at=timezone.now())
        return result

    def __str__(self):
        return f"{self.name} · {self.area}"


class PinAttempt(models.Model):
    device = models.ForeignKey(OperationalDevice, on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Control de intentos de PIN"
        verbose_name_plural = "Controles de intentos de PIN"
        constraints = [models.UniqueConstraint(fields=("device", "user"), name="operations_pin_device_user_unique")]


class OperationalSession(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    binding_hash = models.CharField(max_length=64, editable=False)
    auth_hash = models.CharField(max_length=64, editable=False)
    device = models.ForeignKey(OperationalDevice, on_delete=models.PROTECT, related_name="operational_sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="operational_sessions")
    area = models.ForeignKey("venues.Area", on_delete=models.PROTECT)
    created_at = models.DateTimeField(default=timezone.now)
    last_activity_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Sesión operativa"
        verbose_name_plural = "Sesiones operativas"
        constraints = [models.UniqueConstraint(fields=("device", "binding_hash"), condition=models.Q(revoked_at__isnull=True), name="operations_one_session_per_browser")]


class CashPinAttempt(models.Model):
    register = models.ForeignKey("cash.CashRegister", on_delete=models.PROTECT)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_failed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=("register", "user"), name="operations_cash_pin_register_user")]


class CashAccessSession(models.Model):
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    binding_hash = models.CharField(max_length=64, editable=False)
    auth_hash = models.CharField(max_length=64, editable=False)
    register = models.ForeignKey("cash.CashRegister", on_delete=models.PROTECT, related_name="cash_access_sessions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    business_day = models.ForeignKey("cash.BusinessDay", on_delete=models.PROTECT, null=True, blank=True)
    cash_session = models.ForeignKey("cash.CashSession", on_delete=models.PROTECT, null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    last_activity_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [("request_cash_withdrawal", "Puede solicitar retiros desde caja")]
        constraints = [models.UniqueConstraint(fields=("register", "binding_hash"), condition=models.Q(revoked_at__isnull=True), name="operations_cash_access_browser")]
