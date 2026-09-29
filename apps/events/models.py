"""Eventos: pools individuales y de mesas independientes de reservas normales."""
import secrets
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


def token():
    return secrets.token_urlsafe(32)


def purchase_code():
    return 'BP-C-' + secrets.token_hex(6).upper()


def ticket_number():
    return 'BP-E' + timezone.localdate().strftime('%y') + '-' + secrets.token_hex(6).upper()


class ProofStorage(FileSystemStorage):
    @property
    def base_location(self):
        return settings.EVENT_PROOF_ROOT

    @property
    def location(self):
        return str(Path(self.base_location).resolve())

    def url(self, name):
        raise ValueError('Comprobante privado.')


def proof_storage():
    return ProofStorage()


def image_path(instance, filename):
    return 'events/' + secrets.token_hex(24) + Path(filename).suffix.lower()


class Record(models.Model):
    class Meta:
        abstract = True
        default_permissions = ()

    def delete(self, *args, **kwargs):
        raise ValidationError('Conserva el historial: desactiva o cancela mediante los servicios.')


class EventSettings(Record):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    purchase_hold_minutes = models.PositiveIntegerField(default=15, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    payment_window_minutes = models.PositiveIntegerField(default=15, validators=[MinValueValidator(1), MaxValueValidator(1440)])
    # Instrucciones visibles; no credenciales bancarias ni integración bancaria.
    transfer_instructions = models.TextField(blank=True, default='Solicita los datos de transferencia al establecimiento e incluye la referencia y el comprobante.')

    class Meta(Record.Meta):
        constraints = [models.CheckConstraint(condition=Q(id=1), name='event_settings_singleton')]


class Event(Record):
    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Borrador'
        PUBLISHED = 'PUBLISHED', 'Publicado'
        FINISHED = 'FINISHED', 'Finalizado'
        RESCHEDULED = 'RESCHEDULED', 'Reprogramado'
        CANCELLED = 'CANCELLED', 'Cancelado'

    name = models.CharField('Nombre', max_length=140)
    slug = models.SlugField(max_length=180, unique=True)
    artist_name = models.CharField('Artista / DJ', max_length=140, blank=True)
    description = models.TextField('Descripción', blank=True)
    image = models.ImageField('Imagen', upload_to=image_path, blank=True)
    starts_at = models.DateTimeField('Inicio')
    ends_at = models.DateTimeField('Fin')
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    ticket_sales_enabled = models.BooleanField('Venta de entradas habilitada', default=True)
    maximum_capacity = models.PositiveIntegerField('Aforo máximo', default=0)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(Record.Meta):
        ordering = ['-starts_at', '-pk']
        indexes = [models.Index(fields=['status', 'starts_at'], name='event_status_start')]
        constraints = [models.CheckConstraint(condition=Q(ends_at__gt=F('starts_at')), name='event_positive_interval')]
        permissions = [(p, label) for p, label in [
            ('view_events', 'Ver eventos'), ('create_event', 'Crear evento'), ('change_event', 'Editar evento'),
            ('publish_event', 'Publicar evento'), ('duplicate_event', 'Duplicar evento'), ('reschedule_event', 'Reprogramar evento'),
            ('cancel_event', 'Cancelar evento'), ('manage_event_ticket_types', 'Configurar entradas'), ('manage_event_tables', 'Configurar mesas de evento'),
            ('view_event_purchases', 'Ver compras de evento'), ('verify_event_payment', 'Confirmar transferencia de evento'),
            ('reject_event_payment', 'Rechazar transferencia de evento'), ('issue_courtesy_tickets', 'Emitir cortesías'),
            ('view_event_capacity', 'Ver aforo'), ('scan_event_ticket', 'Escanear entrada')]]

    def clean(self):
        if self.starts_at and self.ends_at:
            if timezone.is_naive(self.starts_at) or timezone.is_naive(self.ends_at) or self.ends_at <= self.starts_at:
                raise ValidationError('Inicio y fin deben incluir zona horaria; fin posterior al inicio.')

    @property
    def display_status(self):
        if self.status in ('PUBLISHED', 'RESCHEDULED') and self.starts_at <= timezone.now() <= self.ends_at:
            return 'En curso'
        return self.get_status_display()

    def __str__(self):
        return self.name


class EventTicketType(Record):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='ticket_types')
    name = models.CharField('Nombre', max_length=80)
    price = models.DecimalField('Precio', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    capacity = models.PositiveIntegerField('Cupo individual')
    sale_starts_at = models.DateTimeField('Venta desde')
    sale_ends_at = models.DateTimeField('Venta hasta')
    max_per_purchase = models.PositiveIntegerField('Máximo por compra', default=10, validators=[MinValueValidator(1), MaxValueValidator(100)])
    sort_order = models.PositiveIntegerField('Orden', default=0)
    is_active = models.BooleanField('Activo', default=True)
    is_courtesy_type = models.BooleanField('Cortesía (emisión interna)', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(Record.Meta):
        ordering = ['sort_order', 'pk']
        indexes = [models.Index(fields=['event', 'is_active'], name='event_type_active')]
        constraints = [models.CheckConstraint(condition=Q(price__gte=0), name='event_type_price_nonnegative'),
            models.CheckConstraint(condition=Q(sale_ends_at__gte=F('sale_starts_at')), name='event_type_sale_interval'),
            models.CheckConstraint(condition=Q(max_per_purchase__gt=0), name='event_type_positive_max')]

    def clean(self):
        if self.sale_starts_at and self.sale_ends_at:
            if timezone.is_naive(self.sale_starts_at) or timezone.is_naive(self.sale_ends_at) or self.sale_ends_at < self.sale_starts_at:
                raise ValidationError('Ventana de venta inválida.')
        if self.is_courtesy_type and self.price != 0:
            raise ValidationError('Las cortesías deben tener precio cero.')

    def __str__(self):
        return self.name


class EventTableConfiguration(Record):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='table_configurations')
    table = models.ForeignKey('tables.VenueTable', on_delete=models.PROTECT)
    enabled = models.BooleanField('Habilitada', default=True)
    capacity_snapshot = models.PositiveIntegerField('Personas', validators=[MinValueValidator(1)])
    ticket_type = models.ForeignKey(EventTicketType, on_delete=models.PROTECT)
    cover_per_person = models.DecimalField('Cover por persona', max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(Record.Meta):
        constraints = [models.UniqueConstraint(fields=['event', 'table'], name='event_table_unique'),
            models.CheckConstraint(condition=Q(capacity_snapshot__gt=0, cover_per_person__gte=0), name='event_table_values')]

    def clean(self):
        if self.ticket_type_id and self.ticket_type.event_id != self.event_id:
            raise ValidationError('El tipo debe pertenecer al evento.')

    @property
    def total_price(self):
        return self.capacity_snapshot * self.cover_per_person


class EventPurchase(Record):
    class Status(models.TextChoices):
        PENDING_PAYMENT = 'PENDING_PAYMENT', 'Esperando pago'
        PAYMENT_REVIEW = 'PAYMENT_REVIEW', 'Pago por verificar'
        CONFIRMED = 'CONFIRMED', 'Confirmada'
        REJECTED = 'REJECTED', 'Rechazada'
        EXPIRED = 'EXPIRED', 'Expirada'
        CANCELLED = 'CANCELLED', 'Cancelada'

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='purchases')
    secure_token = models.CharField(max_length=64, unique=True, default=token, editable=False)
    public_code = models.CharField(max_length=20, unique=True, default=purchase_code, editable=False)
    customer_name = models.CharField('Nombre', max_length=120)
    customer_phone = models.CharField('Teléfono', max_length=20)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING_PAYMENT, db_index=True)
    hold_expires_at = models.DateTimeField()
    payment_expires_at = models.DateTimeField()
    payment_confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def amount(self):
        table = getattr(self, 'table_reservation', None)
        return table.amount if table else sum((i.subtotal for i in self.items.all()), start=0)

    @property
    def deadline(self):
        return min(self.hold_expires_at, self.payment_expires_at)

    @property
    def effective_expired(self):
        return self.status == 'EXPIRED' or (self.status == 'PENDING_PAYMENT' and self.deadline <= timezone.now())


class EventPurchaseItem(Record):
    purchase = models.ForeignKey(EventPurchase, on_delete=models.PROTECT, related_name='items')
    ticket_type = models.ForeignKey(EventTicketType, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    unit_price_snapshot = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(0)])

    class Meta(Record.Meta):
        constraints = [models.UniqueConstraint(fields=['purchase', 'ticket_type'], name='event_purchase_type_unique'),
            models.CheckConstraint(condition=Q(quantity__gt=0, unit_price_snapshot__gte=0), name='event_item_values')]

    @property
    def subtotal(self):
        return self.quantity * self.unit_price_snapshot


class EventTableReservation(Record):
    event = models.ForeignKey(Event, on_delete=models.PROTECT)
    table_configuration = models.ForeignKey(EventTableConfiguration, on_delete=models.PROTECT, related_name='reservations')
    purchase = models.OneToOneField(EventPurchase, on_delete=models.PROTECT, related_name='table_reservation')
    customer_name = models.CharField(max_length=120)
    customer_phone = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=EventPurchase.Status.choices, default='PENDING_PAYMENT')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)


class EventPurchasePayment(Record):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Por verificar'
        CONFIRMED = 'CONFIRMED', 'Confirmado'
        REJECTED = 'REJECTED', 'Rechazado'

    purchase = models.OneToOneField(EventPurchase, on_delete=models.PROTECT, related_name='payment')
    amount = models.DecimalField('Monto transferido', max_digits=12, decimal_places=2)
    reference = models.CharField('Referencia', max_length=160)
    proof_image = models.ImageField('Comprobante', storage=proof_storage, upload_to=image_path)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING, db_index=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)

    class Meta(Record.Meta):
        constraints = [models.CheckConstraint(condition=Q(amount__gt=0), name='event_payment_positive')]


class EventTicket(Record):
    class Status(models.TextChoices):
        VALID = 'VALID', 'Válida'
        USED = 'USED', 'Utilizada'
        CANCELLED = 'CANCELLED', 'Cancelada'

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='tickets')
    purchase = models.ForeignKey(EventPurchase, on_delete=models.PROTECT, related_name='tickets', null=True, blank=True)
    ticket_type = models.ForeignKey(EventTicketType, on_delete=models.PROTECT)
    table_reservation = models.ForeignKey(EventTableReservation, on_delete=models.PROTECT, null=True, blank=True, related_name='tickets')
    ticket_number = models.CharField(max_length=30, unique=True, default=ticket_number, editable=False)
    qr_token = models.CharField(max_length=64, unique=True, default=token, editable=False)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.VALID, db_index=True)
    issued_at = models.DateTimeField(default=timezone.now)
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    courtesy_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EventScheduleHistory(Record):
    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name='schedule_history')
    old_starts_at = models.DateTimeField()
    old_ends_at = models.DateTimeField()
    new_starts_at = models.DateTimeField()
    new_ends_at = models.DateTimeField()
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)


class GuardLoginAttempt(Record):
    """Límite por identificador opaco (usuario/IP); nunca almacena el PIN."""
    key = models.CharField(max_length=64, unique=True)
    failed = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
