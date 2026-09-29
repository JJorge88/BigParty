import secrets
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q


def token():
    return secrets.token_urlsafe(32)


def public_code():
    return 'BP-R-' + ''.join(secrets.choice('ABCDEFGHJKLMNPQRSTUVWXYZ23456789') for _ in range(10))


class PrivateProofStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.RESERVATION_PROOF_ROOT

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def url(self, name):
        raise ValueError('Los comprobantes privados solo se sirven desde Gerencia.')


def proof_storage():
    return PrivateProofStorage()


def proof_path(instance, filename):
    return f'{secrets.token_hex(24)}{Path(filename).suffix.lower()}'


class AdvanceType(models.TextChoices):
    FIXED = 'FIXED', 'Monto fijo'
    PERCENTAGE = 'PERCENTAGE', 'Porcentaje'


class AdvanceApplication(models.TextChoices):
    CREDIT = 'CREDIT', 'Abono al consumo'
    FEE = 'FEE', 'Cargo de reserva'


class ReservationSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    reservations_enabled = models.BooleanField('Reservas habilitadas', default=True)
    default_duration_minutes = models.PositiveIntegerField('Duración en minutos', default=180, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    public_hold_minutes = models.PositiveIntegerField('Retención de solicitud (min)', default=15, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    payment_window_minutes = models.PositiveIntegerField('Ventana de pago (min)', default=15, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    advance_payment_enabled = models.BooleanField('Solicitar anticipo por defecto', default=False)
    advance_payment_type = models.CharField('Tipo de anticipo', max_length=12, choices=AdvanceType.choices, default=AdvanceType.FIXED)
    advance_payment_value = models.DecimalField('Valor del anticipo', max_digits=12, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    advance_payment_application = models.CharField('Aplicación', max_length=8, choices=AdvanceApplication.choices, default=AdvanceApplication.CREDIT)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(id=1), name='reservation_settings_singleton')]
        verbose_name_plural = 'configuración de reservas'

    def clean(self):
        if self.advance_payment_enabled and self.advance_payment_value <= 0:
            raise ValidationError('El anticipo debe ser mayor que cero.')
        if self.advance_payment_type == 'PERCENTAGE' and self.advance_payment_value > 100:
            raise ValidationError('El porcentaje no puede superar 100.')


class Reservation(models.Model):
    class ReservationType(models.TextChoices):
        NORMAL = 'NORMAL', 'Reserva normal'

    class Status(models.TextChoices):
        PENDING_REVIEW = 'PENDING_REVIEW', 'Pendiente'
        AWAITING_PAYMENT = 'AWAITING_PAYMENT', 'Esperando pago'
        PAYMENT_REVIEW = 'PAYMENT_REVIEW', 'Pago por verificar'
        CONFIRMED = 'CONFIRMED', 'Confirmada'
        ARRIVED = 'ARRIVED', 'Llegó'
        REJECTED = 'REJECTED', 'Rechazada'
        EXPIRED = 'EXPIRED', 'Expirada'
        CANCELLED = 'CANCELLED', 'Cancelada'
        NO_SHOW = 'NO_SHOW', 'No llegó'

    secure_token = models.CharField(max_length=64, unique=True, default=token, editable=False)
    public_code = models.CharField(max_length=20, unique=True, default=public_code, editable=False)
    reservation_type = models.CharField(max_length=8, choices=ReservationType.choices, default=ReservationType.NORMAL)
    table = models.ForeignKey('tables.VenueTable', on_delete=models.PROTECT, related_name='reservations')
    area = models.ForeignKey('venues.Area', on_delete=models.PROTECT)
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=20)
    reservation_date = models.DateField(db_index=True)
    start_time = models.TimeField()
    starts_at = models.DateTimeField(db_index=True)
    ends_at = models.DateTimeField()
    duration_minutes = models.PositiveIntegerField(default=180, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    party_size = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_REVIEW, db_index=True)
    payment_required = models.BooleanField(default=False)
    payment_type = models.CharField(max_length=12, choices=AdvanceType.choices, default=AdvanceType.FIXED)
    payment_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_base_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    payment_application = models.CharField(max_length=8, choices=AdvanceApplication.choices, default=AdvanceApplication.CREDIT)
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    payment_expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    arrival_confirmed_at = models.DateTimeField(null=True, blank=True)
    arrival_confirmed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    cancellation_reason = models.TextField(blank=True)
    no_show_at = models.DateTimeField(null=True, blank=True)
    no_show_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    no_show_reason = models.TextField(blank=True)
    order = models.OneToOneField('orders.TableOrder', on_delete=models.PROTECT, null=True, blank=True, related_name='reservation')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        permissions = [(name, label) for name, label in (
            ('view_reservations', 'Ver reservas'), ('create_reservation', 'Crear reserva'),
            ('approve_reservation', 'Aprobar reserva'), ('reject_reservation', 'Rechazar reserva'),
            ('verify_reservation_payment', 'Confirmar pago de reserva'), ('reject_reservation_payment', 'Rechazar pago de reserva'),
            ('cancel_reservation', 'Cancelar reserva'), ('confirm_reservation_arrival', 'Confirmar llegada'),
            ('mark_reservation_no_show', 'Marcar no llegó'), ('configure_reservations', 'Configurar reservas'))]
        indexes = [models.Index(fields=['table', 'reservation_date'], name='reservation_table_date')]
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=models.F('starts_at')), name='reservation_positive_interval'),
                       models.CheckConstraint(condition=Q(party_size__gt=0), name='reservation_positive_party')]
        ordering = ['starts_at', 'pk']

    def __str__(self):
        return self.public_code

    @property
    def deadline(self):
        return self.hold_expires_at if self.status == 'PENDING_REVIEW' else self.payment_expires_at if self.status == 'AWAITING_PAYMENT' else None


class ReservationPayment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Por verificar'
        CONFIRMED = 'CONFIRMED', 'Confirmado'
        REJECTED = 'REJECTED', 'Rechazado'

    reservation = models.OneToOneField(Reservation, on_delete=models.PROTECT, related_name='payment')
    method = models.CharField(max_length=8, choices=[('TRANSFER', 'Transferencia')], default='TRANSFER')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=160)
    proof_image = models.ImageField(storage=proof_storage, upload_to=proof_path, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='reservation_payment_positive')]


class ReservationCredit(models.Model):
    order = models.ForeignKey('orders.TableOrder', on_delete=models.PROTECT, related_name='reservation_credits')
    payment = models.OneToOneField(ReservationPayment, on_delete=models.PROTECT, related_name='credit')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='reservation_credit_positive')]


class ReservationCreditAllocation(models.Model):
    credit = models.ForeignKey(ReservationCredit, on_delete=models.PROTECT, related_name='allocations')
    order_line = models.ForeignKey('orders.OrderLine', on_delete=models.PROTECT, related_name='reservation_credit_allocations')
    unit_number = models.PositiveIntegerField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['credit', 'order_line', 'unit_number'], name='reservation_credit_unit_unique'),
                       models.CheckConstraint(condition=Q(amount__gt=0, unit_number__gt=0), name='reservation_allocation_positive')]
