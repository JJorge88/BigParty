"""Mutaciones serializadas por Event: orden de bloqueo evento → compra → ticket.

Todos los escritores del aforo toman el mismo bloqueo PostgreSQL. No se usa
un contador cacheado ni se confía en disponibilidad calculada por el cliente.
"""
from apps.sync.services import sync_atomic, save_tracked
from datetime import timedelta
from decimal import Decimal, InvalidOperation
import re
import warnings
from PIL import Image
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify
from apps.audit.models import AuditLog
from .models import (Event, EventSettings, EventTicketType, EventTableConfiguration, EventPurchase,
    EventPurchaseItem, EventTableReservation, EventPurchasePayment, EventTicket, EventScheduleHistory, token)
from .queries import (LIVE_STATUSES, active_purchases, get_settings, get_event_capacity_summary,
    configuration_summary, type_committed, table_available, build_event_access_snapshot)


def require(user, permission):
    if not user or not user.is_active or not user.has_perm('events.' + permission):
        raise PermissionDenied('No tienes permiso para esta operación.')


def audit(action, obj, user=None, **data):
    AuditLog.objects.create(user=user, action='events.' + action, entity=obj._meta.label, entity_id=str(obj.pk), data=data)


def save(obj):
    obj.full_clean()
    save_tracked(obj)
    return obj


def locked(event):
    return Event.objects.select_for_update().get(pk=event.pk)


def money(value):
    try:
        number = Decimal(str(value))
        if not number.is_finite() or number < 0 or number > Decimal('9999999999.99') or number != number.quantize(Decimal('.01')):
            raise ValueError
        return number
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Monto inválido: usa hasta dos decimales.')


def positive_quantity(value, maximum=None):
    if type(value) is not int or value < 1 or (maximum and value > maximum):
        raise ValidationError('Cantidad fuera del límite permitido.')
    return value


def validate_image(upload):
    if not upload or upload.size > 5 * 1024 * 1024:
        raise ValidationError('Adjunta una imagen JPEG, PNG o WebP de hasta 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            picture = Image.open(upload)
            if picture.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError
            extension = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp'}[picture.format]
            picture.verify()
        upload.seek(0)
        upload.name = 'image' + extension
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValidationError('Imagen inválida. Usa JPEG, PNG o WebP.')
    return upload


def mutable(event):
    if event.status in ('CANCELLED', 'FINISHED'):
        raise ValidationError('El evento ya está cerrado.')


def selling(event):
    if event.status not in LIVE_STATUSES or not event.ticket_sales_enabled or event.ends_at <= timezone.now():
        raise ValidationError('Este evento no tiene ventas abiertas.')


def enforce_capacity(event):
    if get_event_capacity_summary(event)['remaining'] < 0:
        raise ValidationError('El aforo no puede ser menor que los accesos comprometidos.')
    if event.status != 'DRAFT' and configuration_summary(event)['total'] > event.maximum_capacity:
        raise ValidationError('Entradas y mesas configuradas superan el aforo máximo.')


@sync_atomic('cloud')
@transaction.atomic
def create_event(user, **data):
    require(user, 'create_event')
    allowed = {'name', 'artist_name', 'description', 'image', 'starts_at', 'ends_at', 'ticket_sales_enabled', 'maximum_capacity'}
    if set(data) - allowed:
        raise ValidationError('Campo no editable.')
    if data.get('image'):
        validate_image(data['image'])
    event = save(Event(created_by=user, slug=(slugify(data.get('name', 'evento'))[:145] or 'evento') + '-' + token()[:12].lower(), **data))
    audit('created', event, user)
    return event


@sync_atomic('cloud')
@transaction.atomic
def edit_event(event, user, **data):
    require(user, 'change_event')
    event = locked(event)
    mutable(event)
    allowed = {'name', 'artist_name', 'description', 'image', 'starts_at', 'ends_at', 'ticket_sales_enabled', 'maximum_capacity'}
    if set(data) - allowed:
        raise ValidationError('Campo no editable.')
    if event.status != 'DRAFT' and any(key in data and data[key] != getattr(event, key) for key in ('starts_at', 'ends_at')):
        raise ValidationError('Para cambiar fechas de un evento publicado usa Reprogramar.')
    if data.get('image') and data['image'] != event.image:
        validate_image(data['image'])
    for key, value in data.items():
        setattr(event, key, value)
    save(event)
    enforce_capacity(event)
    audit('edited', event, user, maximum_capacity=event.maximum_capacity)
    return event


@sync_atomic('cloud')
@transaction.atomic
def configure_settings(user, **data):
    require(user, 'change_event')
    settings = get_settings()
    for key in ('purchase_hold_minutes', 'payment_window_minutes', 'transfer_instructions'):
        if key in data:
            setattr(settings, key, data[key])
    save(settings)
    audit('settings', settings, user)
    return settings


@sync_atomic('cloud')
@transaction.atomic
def save_ticket_type(event, user, ticket_type=None, **data):
    require(user, 'manage_event_ticket_types')
    event = locked(event)
    mutable(event)
    row = EventTicketType.objects.get(pk=ticket_type.pk, event=event) if ticket_type else EventTicketType(event=event)
    allowed = {'name', 'price', 'capacity', 'sale_starts_at', 'sale_ends_at', 'max_per_purchase', 'sort_order', 'is_active', 'is_courtesy_type'}
    if set(data) - allowed:
        raise ValidationError('Campo no editable.')
    committed = type_committed(row) if row.pk else 0
    if row.pk and row.is_courtesy_type != data.get('is_courtesy_type', row.is_courtesy_type) and committed:
        raise ValidationError('Un tipo utilizado conserva su clasificación de cortesía.')
    for key, value in data.items():
        setattr(row, key, money(value) if key == 'price' else value)
    if row.capacity < committed:
        raise ValidationError('El cupo no puede bajar de la cantidad comprometida.')
    save(row)
    enforce_capacity(event)
    audit('ticket_type_saved', row, user, capacity=row.capacity, active=row.is_active)
    return row


@sync_atomic('cloud')
@transaction.atomic
def save_event_table(event, user, table, ticket_type, cover_per_person, enabled=True):
    require(user, 'manage_event_tables')
    event = locked(event)
    mutable(event)
    row = EventTableConfiguration.objects.filter(event=event, table=table).first()
    if row and row.reservations.filter(purchase__in=active_purchases(event)).exists():
        raise ValidationError('La mesa tiene una compra comprometida; conserva su configuración.')
    if not table.is_active or table.operational_status != 'ACTIVE' or not table.area.is_active:
        raise ValidationError('La mesa debe estar activa.')
    if ticket_type.event_id != event.pk or not ticket_type.is_active:
        raise ValidationError('Selecciona un tipo activo del evento.')
    row = row or EventTableConfiguration(event=event, table=table, capacity_snapshot=table.capacity)
    row.ticket_type, row.cover_per_person, row.enabled = ticket_type, money(cover_per_person), enabled
    save(row)
    enforce_capacity(event)
    audit('table_saved', row, user, capacity=row.capacity_snapshot)
    return row


def validate_event_for_publication(event):
    errors = []
    def error(field, message):
        errors.append({'field': field, 'message': message})
    try:
        event.full_clean()
    except ValidationError as exc:
        error('information', ' '.join(exc.messages))
    if not event.image:
        error('image', 'Agrega la imagen del evento.')
    if event.maximum_capacity <= 0:
        error('maximum_capacity', 'Define un aforo mayor que cero.')
    types = event.ticket_types.filter(is_active=True)
    if event.ticket_sales_enabled and not types.filter(is_courtesy_type=False, price__gt=0).exists():
        error('ticket_types', 'Agrega al menos un tipo de entrada de venta activo.')
    if configuration_summary(event)['total'] > event.maximum_capacity:
        error('capacity', 'La suma de entradas individuales y mesas supera el aforo.')
    for row in event.ticket_types.all():
        try:
            row.full_clean()
        except ValidationError as exc:
            error('ticket_types', ' '.join(exc.messages))
    for row in event.table_configurations.filter(enabled=True).select_related('table__area', 'ticket_type'):
        if not row.table.is_active or row.table.operational_status != 'ACTIVE' or not row.table.area.is_active or not row.ticket_type.is_active or row.ticket_type.event_id != event.pk:
            error('tables', 'Hay mesas o tipos de acceso inactivos o inválidos.')
        if row.cover_per_person <= 0:
            error('tables', 'Las mesas de venta requieren cover mayor que cero.')
    return errors


@sync_atomic('cloud')
@transaction.atomic
def publish_event(event, user):
    require(user, 'publish_event')
    event = locked(event)
    if event.status != 'DRAFT':
        raise ValidationError('Solo se publica un borrador.')
    errors = validate_event_for_publication(event)
    if errors:
        raise ValidationError([e['message'] for e in errors])
    event.status, event.published_at = 'PUBLISHED', timezone.now()
    save(event)
    audit('published', event, user)
    return event


@sync_atomic('cloud')
@transaction.atomic
def duplicate_event(event, user):
    require(user, 'duplicate_event')
    source = locked(event)
    data = {key: getattr(source, key) for key in ('name', 'artist_name', 'description', 'image', 'starts_at', 'ends_at', 'ticket_sales_enabled', 'maximum_capacity')}
    data['name'] = (source.name[:132] + ' · copia')
    copy = save(Event(created_by=user, slug=(slugify(source.name)[:140] or 'evento') + '-' + token()[:12].lower(), **data))
    types = {}
    for row in source.ticket_types.all():
        old_pk = row.pk
        row.pk, row.event = None, copy
        save(row)
        types[old_pk] = row
    for row in source.table_configurations.all():
        row.pk, row.event, row.ticket_type = None, copy, types[row.ticket_type_id]
        save(row)
    audit('duplicated', copy, user, source=source.pk)
    return copy


@sync_atomic('cloud')
@transaction.atomic
def create_purchase(event, customer_name, customer_phone, quantities=None, table_configuration=None):
    event = locked(event)
    selling(event)
    name, phone = customer_name.strip(), customer_phone.strip()
    if not name or not re.fullmatch(r'\+?[\d ()-]{8,20}', phone) or not 8 <= sum(c.isdigit() for c in phone) <= 15:
        raise ValidationError('Escribe nombre y teléfono válidos.')
    quantities = quantities or {}
    if bool(quantities) == bool(table_configuration):
        raise ValidationError('Elige entradas individuales o una mesa completa.')
    now, config = timezone.now(), get_settings()
    planned, total_quantity = [], 0
    table = None
    if table_configuration:
        table = EventTableConfiguration.objects.select_related('table__area', 'ticket_type').get(pk=table_configuration.pk, event=event)
        if not table_available(table, now) or not table.table.is_active or table.table.operational_status != 'ACTIVE' or not table.table.area.is_active or not table.ticket_type.is_active or table.cover_per_person <= 0:
            raise ValidationError('Esta mesa ya no está disponible.')
        total_quantity = table.capacity_snapshot
    else:
        if len(quantities) > 100:
            raise ValidationError('Demasiados tipos en una compra.')
        for type_id, quantity in quantities.items():
            row = EventTicketType.objects.filter(pk=type_id, event=event).first()
            if not row or not row.is_active or row.is_courtesy_type or row.price <= 0 or not row.sale_starts_at <= now <= row.sale_ends_at:
                raise ValidationError('Un tipo seleccionado no está en venta.')
            positive_quantity(quantity, row.max_per_purchase)
            if type_committed(row, now) + quantity > row.capacity:
                raise ValidationError('No hay cupo suficiente para ' + row.name + '.')
            planned.append((row, quantity))
            total_quantity += quantity
    if total_quantity > get_event_capacity_summary(event, now)['remaining']:
        raise ValidationError('No hay aforo disponible para esta compra.')
    purchase = save(EventPurchase(event=event, customer_name=name, customer_phone=phone,
        hold_expires_at=now+timedelta(minutes=config.purchase_hold_minutes), payment_expires_at=now+timedelta(minutes=config.payment_window_minutes)))
    for row, quantity in planned:
        save(EventPurchaseItem(purchase=purchase, ticket_type=row, quantity=quantity, unit_price_snapshot=row.price))
    if table:
        save(EventTableReservation(event=event, table_configuration=table, purchase=purchase,
            customer_name=name, customer_phone=phone, amount=table.total_price))
    audit('purchase_created', purchase, quantity=total_quantity)
    return purchase


def lock_purchase(purchase):
    event = locked(purchase.event)
    return event, EventPurchase.objects.select_for_update().get(pk=purchase.pk)


def set_purchase_status(purchase, status):
    purchase.status = status
    save(purchase)
    purchase_table = getattr(purchase, 'table_reservation', None)
    if purchase_table:
        purchase_table.status = status
        if status == 'CONFIRMED':
            purchase_table.confirmed_at = timezone.now()
        save(purchase_table)


@sync_atomic('cloud')
@transaction.atomic
def submit_event_payment(purchase, amount, reference, proof_image):
    event, purchase = lock_purchase(purchase)
    if event.status not in LIVE_STATUSES or purchase.status != 'PENDING_PAYMENT' or purchase.effective_expired:
        raise ValidationError('La compra ya no admite comprobantes.')
    reference = reference.strip()
    if not reference or money(amount) != purchase.amount or money(amount) <= 0:
        raise ValidationError('Referencia obligatoria y monto igual al total de la compra.')
    validate_image(proof_image)
    payment = save(EventPurchasePayment(purchase=purchase, amount=money(amount), reference=reference, proof_image=proof_image))
    set_purchase_status(purchase, 'PAYMENT_REVIEW')
    audit('payment_submitted', payment)
    return payment


def _generate_tickets(purchase, user):
    if purchase.status != 'CONFIRMED':
        raise ValidationError('Confirma la compra antes de emitir entradas.')
    existing = list(purchase.tickets.order_by('pk'))
    table = getattr(purchase, 'table_reservation', None)
    planned = [(table.table_configuration.ticket_type, table.table_configuration.capacity_snapshot)] if table else [(i.ticket_type, i.quantity) for i in purchase.items.select_related('ticket_type')]
    expected = sum(q for _, q in planned)
    if existing:
        if len(existing) != expected:
            raise ValidationError('Emisión inconsistente; requiere revisión interna.')
        return existing
    tickets = []
    for kind, quantity in planned:
        for _ in range(quantity):
            tickets.append(save(EventTicket(event=purchase.event, purchase=purchase, ticket_type=kind, table_reservation=table, created_by=user)))
    audit('tickets_issued', purchase, user, quantity=len(tickets))
    return tickets


@sync_atomic('cloud')
@transaction.atomic
def generate_purchase_tickets(purchase, user):
    require(user, 'verify_event_payment')
    event, purchase = lock_purchase(purchase)
    if event.status == 'CANCELLED':
        raise ValidationError('Evento cancelado.')
    return _generate_tickets(purchase, user)


@sync_atomic('cloud')
@transaction.atomic
def confirm_event_payment(payment, user):
    require(user, 'verify_event_payment')
    event, purchase = lock_purchase(payment.purchase)
    payment = EventPurchasePayment.objects.select_for_update().get(pk=payment.pk)
    if payment.status == 'CONFIRMED' and purchase.status == 'CONFIRMED':
        return list(purchase.tickets.order_by('pk'))
    if event.status not in LIVE_STATUSES or purchase.status != 'PAYMENT_REVIEW' or payment.status != 'PENDING':
        raise ValidationError('Este pago ya no puede confirmarse.')
    if payment.amount != purchase.amount:
        raise ValidationError('El pago no coincide con la compra.')
    payment.status, payment.reviewed_by, payment.reviewed_at = 'CONFIRMED', user, timezone.now()
    save(payment)
    purchase.payment_confirmed_at = timezone.now()
    set_purchase_status(purchase, 'CONFIRMED')
    tickets = _generate_tickets(purchase, user)
    enforce_capacity(event)
    audit('payment_confirmed', payment, user)
    return tickets


@sync_atomic('cloud')
@transaction.atomic
def reject_event_payment(payment, user, reason):
    require(user, 'reject_event_payment')
    event, purchase = lock_purchase(payment.purchase)
    payment = EventPurchasePayment.objects.select_for_update().get(pk=payment.pk)
    if not reason.strip() or payment.status != 'PENDING' or purchase.status != 'PAYMENT_REVIEW':
        raise ValidationError('Pago no revisable o falta el motivo del rechazo.')
    payment.status, payment.reviewed_by, payment.reviewed_at, payment.rejection_reason = 'REJECTED', user, timezone.now(), reason.strip()
    save(payment)
    set_purchase_status(purchase, 'REJECTED')
    audit('payment_rejected', payment, user, reason=reason.strip())
    return payment


@sync_atomic('cloud')
@transaction.atomic
def issue_courtesy_tickets(event, ticket_type, quantity, created_by, reason=''):
    require(created_by, 'issue_courtesy_tickets')
    event = locked(event)
    if event.status not in LIVE_STATUSES:
        raise ValidationError('Publica el evento antes de emitir cortesías.')
    kind = EventTicketType.objects.get(pk=ticket_type.pk, event=event)
    positive_quantity(quantity, 100)
    if not kind.is_active or not kind.is_courtesy_type or kind.price != 0:
        raise ValidationError('Elige un tipo activo de cortesía a precio cero.')
    if type_committed(kind) + quantity > kind.capacity or quantity > get_event_capacity_summary(event)['remaining']:
        raise ValidationError('No hay cupo para estas cortesías.')
    tickets = [save(EventTicket(event=event, ticket_type=kind, created_by=created_by, courtesy_reason=reason.strip())) for _ in range(quantity)]
    audit('courtesy_issued', event, created_by, quantity=quantity, reason=reason.strip())
    return tickets


@sync_atomic('cloud')
@transaction.atomic
def reschedule_event(event, user, starts_at, ends_at, reason):
    require(user, 'reschedule_event')
    event = locked(event)
    if event.status not in LIVE_STATUSES or not reason.strip():
        raise ValidationError('Reprograma un evento publicado e indica el motivo.')
    history = EventScheduleHistory(event=event, old_starts_at=event.starts_at, old_ends_at=event.ends_at,
        new_starts_at=starts_at, new_ends_at=ends_at, changed_by=user, reason=reason.strip())
    event.starts_at, event.ends_at, event.status = starts_at, ends_at, 'RESCHEDULED'
    save(event)
    save(history)
    audit('rescheduled', event, user, reason=reason.strip())
    return event


@sync_atomic('cloud')
@transaction.atomic
def cancel_event(event, user, reason):
    require(user, 'cancel_event')
    event = locked(event)
    if not reason.strip():
        raise ValidationError('Indica el motivo de cancelación.')
    if event.status == 'CANCELLED':
        return event
    event.status, event.cancellation_reason = 'CANCELLED', reason.strip()
    save(event)
    now = timezone.now()
    for ticket in event.tickets.exclude(status='CANCELLED'):
        ticket.status, ticket.cancelled_at = 'CANCELLED', now
        save(ticket)
        audit('ticket_cancelled', ticket, user, reason=reason.strip())
    for purchase in event.purchases.filter(status__in=['PENDING_PAYMENT', 'PAYMENT_REVIEW']):
        purchase.cancelled_at, purchase.cancellation_reason = now, reason.strip()
        set_purchase_status(purchase, 'CANCELLED')
    audit('cancelled', event, user, reason=reason.strip())
    return event


@sync_atomic('cloud')
@transaction.atomic
def finish_event(event, user):
    require(user, 'change_event')
    event = locked(event)
    if event.status not in LIVE_STATUSES:
        raise ValidationError('Solo se finalizan eventos publicados.')
    if event.purchases.filter(status='PAYMENT_REVIEW').exists():
        raise ValidationError('Revisa los pagos pendientes antes de finalizar.')
    event.status = 'FINISHED'
    save(event)
    audit('finished', event, user)
    return event


@sync_atomic('cloud')
def expire_event_purchases(now=None):
    now = now or timezone.now()
    count = 0
    for event_id in EventPurchase.objects.filter(status='PENDING_PAYMENT').values_list('event_id', flat=True).distinct():
        with transaction.atomic():
            event = Event.objects.select_for_update().get(pk=event_id)
            for purchase in event.purchases.filter(status='PENDING_PAYMENT'):
                if purchase.deadline <= now:
                    set_purchase_status(purchase, 'EXPIRED')
                    audit('purchase_expired', purchase)
                    count += 1
    return count


@sync_atomic('cloud')
@transaction.atomic
def validate_and_use_ticket(token, guard_user):
    require(guard_user, 'scan_event_ticket')
    if guard_user.role != 'GUARDIA':
        raise PermissionDenied('Acceso exclusivo para guardias.')
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return {'result': 'INVALID', 'label': 'Inválida'}
    identity = EventTicket.objects.filter(qr_token=token).values('pk', 'event_id').first()
    if not identity:
        return {'result': 'INVALID', 'label': 'Inválida'}
    event = Event.objects.select_for_update().get(pk=identity['event_id'])
    ticket = EventTicket.objects.select_for_update().select_related('ticket_type').get(pk=identity['pk'])
    data = {'event': event.name, 'ticket_type': ticket.ticket_type.name}
    if event.status == 'CANCELLED' or ticket.status == 'CANCELLED':
        return {**data, 'result': 'CANCELLED', 'label': 'Cancelada'}
    if ticket.status == 'USED':
        audit('scan_duplicate', ticket, guard_user)
        return {**data, 'result': 'USED', 'label': 'Ya utilizada', 'used_at': timezone.localtime(ticket.used_at).isoformat()}
    if event.status not in LIVE_STATUSES:
        return {**data, 'result': 'INVALID', 'label': 'Inválida'}
    ticket.status, ticket.used_at, ticket.used_by = 'USED', timezone.now(), guard_user
    save(ticket)
    audit('scan_valid', ticket, guard_user)
    return {**data, 'result': 'VALID', 'label': 'Válida', 'used_at': timezone.localtime(ticket.used_at).isoformat()}
