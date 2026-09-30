"""Configuración administrativa mínima; los secretos permanecen en el entorno."""
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from decimal import Decimal
from django.db import models
from django.db.models import Q
from apps.payments.models import Payment


class BusinessSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    business_name = models.CharField('nombre del negocio', max_length=100, default='BIG PARTY')
    timezone = models.CharField('zona horaria', max_length=64, default='America/Guatemala', editable=False)
    currency_code = models.CharField('moneda', max_length=3, default='GTQ', editable=False)
    currency_symbol = models.CharField('símbolo', max_length=4, default='Q', editable=False)
    latitude = models.DecimalField('latitud', max_digits=18, decimal_places=15,
        default=Decimal('14.559363833208103'), validators=[MinValueValidator(-90), MaxValueValidator(90)])
    longitude = models.DecimalField('longitud', max_digits=18, decimal_places=15,
        default=Decimal('-89.352664911655140'), validators=[MinValueValidator(-180), MaxValueValidator(180)])
    address_text = models.CharField('dirección pública', max_length=300, blank=True)
    public_phone = models.CharField('teléfono / WhatsApp', max_length=16, blank=True,
        help_text='Opcional. Incluye + y el código de país; sin espacios. Déjalo vacío para ocultar contacto.',
        validators=[RegexValidator(r'^\+[1-9][0-9]{7,14}$', 'Usa formato internacional: + seguido del código de país y número.')])
    minimum_entry_age = models.PositiveSmallIntegerField('edad mínima', default=18,
        validators=[MinValueValidator(1), MaxValueValidator(99)])
    identification_text = models.TextField('identificación', max_length=1500,
        default='Para ingresar deberás presentar un documento de identificación físico y válido.')
    dress_code = models.TextField('código de vestimenta', max_length=1500,
        default='Viste para la ocasión. BIG PARTY mantiene un código de vestimenta casual elegante.')
    dress_code_description = models.TextField('descripción adicional de vestimenta', max_length=1500, blank=True)
    security_text = models.TextField('seguridad', max_length=1500,
        default='Por seguridad de todos, no se permite el ingreso con armas, sustancias ilícitas u objetos que puedan representar un riesgo.')
    admission_policy = models.TextField('política de ingreso', max_length=1500, blank=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name='business_settings_singleton'),
                       models.CheckConstraint(condition=Q(latitude__gte=-90, latitude__lte=90), name='business_latitude_range'),
                       models.CheckConstraint(condition=Q(longitude__gte=-180, longitude__lte=180), name='business_longitude_range'),
                       models.CheckConstraint(condition=Q(minimum_entry_age__gte=1, minimum_entry_age__lte=99), name='business_entry_age_range')]
        permissions = [('view_reports', 'Puede consultar reportes financieros'),
                       ('export_reports_pdf', 'Puede exportar reportes PDF'),
                       ('view_configuration', 'Puede consultar configuración'),
                       ('change_business_configuration', 'Puede configurar el negocio'),
                       ('change_payment_method_configuration', 'Puede configurar métodos de pago'),
                       ('change_bank_transfer_configuration', 'Puede configurar datos de transferencia')]


class BusinessOpeningHours(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, 'Lunes'
        TUESDAY = 1, 'Martes'
        WEDNESDAY = 2, 'Miércoles'
        THURSDAY = 3, 'Jueves'
        FRIDAY = 4, 'Viernes'
        SATURDAY = 5, 'Sábado'
        SUNDAY = 6, 'Domingo'

    weekday = models.PositiveSmallIntegerField('día', choices=Weekday.choices, unique=True)
    is_open = models.BooleanField('abierto', default=False)
    opens_at = models.TimeField('hora de apertura', null=True, blank=True)
    closes_at = models.TimeField('hora de cierre', null=True, blank=True)
    sort_order = models.PositiveSmallIntegerField('orden', default=0)

    class Meta:
        ordering = ('sort_order', 'weekday')
        constraints = [
            models.CheckConstraint(condition=Q(weekday__gte=0, weekday__lte=6), name='opening_hours_weekday_range'),
            models.CheckConstraint(condition=Q(is_open=False) | (
                Q(opens_at__isnull=False, closes_at__isnull=False) & ~Q(opens_at=models.F('closes_at'))),
                name='opening_hours_valid_open_interval')]

    def clean(self):
        if self.is_open and (self.opens_at is None or self.closes_at is None or self.opens_at == self.closes_at):
            raise ValidationError('Para un día abierto, indica una apertura y un cierre diferentes.')

    @property
    def crosses_midnight(self):
        return bool(self.is_open and self.opens_at and self.closes_at and self.closes_at < self.opens_at)


class PaymentMethodSettings(models.Model):
    method = models.CharField('método', max_length=10, choices=Payment.Method.choices, primary_key=True)
    enabled = models.BooleanField('habilitado', default=True)
    display_order = models.PositiveSmallIntegerField('orden', default=0)

    class Meta:
        ordering = ('display_order', 'method')
        constraints = [models.CheckConstraint(condition=Q(method__in=Payment.Method.values), name='known_payment_method')]


class BankTransferSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField('publicar datos de transferencia', default=False)
    bank_name = models.CharField('banco', max_length=100, blank=True)
    account_name = models.CharField('titular', max_length=150, blank=True)
    account_number = models.CharField('número de cuenta', max_length=60, blank=True)
    instructions = models.TextField('instrucciones adicionales', blank=True, max_length=1000)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name='bank_settings_singleton')]

    def clean(self):
        if self.enabled and not all(v.strip() for v in (self.bank_name, self.account_name, self.account_number)):
            raise ValidationError('Para publicar, completa banco, titular y número de cuenta.')

    @property
    def ready(self):
        return self.enabled and all(v.strip() for v in (self.bank_name, self.account_name, self.account_number))
