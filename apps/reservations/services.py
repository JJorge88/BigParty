"""Escrituras autorizadas y serializadas: gate → mesa/reserva → cuenta.

El gate compartido con caja evita carreras llegada/apertura/cierre de jornada.
Las reservas futuras no crean ni requieren una jornada.
"""
from apps.sync.services import sync_atomic, track, save_tracked
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
import warnings

from PIL import Image
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash.guards import lock_operation_gate, lock_open_day
from apps.tables.models import VenueTable
from .models import Reservation, ReservationPayment, ReservationSettings, ReservationCredit
from .queries import get_settings, interval, get_available_tables, blocking_reservations


def require(user, permission):
    if not user or not user.is_active or not user.has_perm('reservations.' + permission):
        raise PermissionDenied('No tienes permiso para esta operación de reservas.')


def log(reservation, action, user=None, **data):
    AuditLog.objects.create(user=user, action='reservations.' + action, entity='reservations.reservation',
                            entity_id=str(reservation.pk), data=data)


def save(obj):
    obj.full_clean()
    save_tracked(obj)
    return obj


def money(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result < 0 or result > Decimal('9999999999.99') or result != result.quantize(Decimal('.01')):
            raise ValueError
        return result.quantize(Decimal('.01'))
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('Indica un monto válido con hasta dos decimales.')


def locked(reservation):
    lock_operation_gate()
    row = Reservation.objects.select_for_update().get(pk=reservation.pk)
    VenueTable.objects.select_for_update().get(pk=row.table_id)
    return row


def check_state(row, *statuses):
    if row.status not in statuses:
        raise ValidationError('El estado de la reserva cambió; vuelve a consultar.')
    if row.deadline and row.deadline <= timezone.now():
        raise ValidationError('El plazo de esta reserva venció. La mesa ya está liberada.')


def payment_terms(row, config, *, payment_required=None, payment_type=None, payment_value=None,
                  payment_application=None, payment_base_amount=0):
    row.payment_required = config.advance_payment_enabled if payment_required is None else payment_required
    if type(row.payment_required) is not bool:
        raise ValidationError('Indica si requiere anticipo.')
    row.payment_type = payment_type or config.advance_payment_type
    row.payment_application = payment_application or config.advance_payment_application
    row.payment_value = money(config.advance_payment_value if payment_value is None else payment_value)
    row.payment_base_amount = money(payment_base_amount)
    if row.payment_type not in ('FIXED', 'PERCENTAGE') or row.payment_application not in ('CREDIT', 'FEE'):
        raise ValidationError('Selecciona un tipo y una aplicación de anticipo válidos.')
    row.payment_amount = Decimal('0.00')
    if row.payment_required:
        if row.payment_type == 'PERCENTAGE':
            if not 0 < row.payment_value <= 100 or not row.payment_base_amount:
                raise ValidationError('Ingresa un porcentaje entre 0 y 100 y una base de consumo estimado mayor que cero.')
            row.payment_amount = (row.payment_base_amount * row.payment_value / 100).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        else:
            row.payment_amount = row.payment_value
        if row.payment_amount <= 0:
            raise ValidationError('El anticipo calculado debe ser mayor que cero.')


def _new(table, customer_name, customer_phone, date, time, party_size, config, duration=None, public=True):
    table = VenueTable.objects.select_for_update().get(pk=table.pk)
    duration = config.default_duration_minutes if duration is None else duration
    start, end = interval(date, time, duration)
    if start < timezone.now():
        raise ValidationError('Selecciona una fecha y hora futuras.')
    if not config.reservations_enabled:
        raise ValidationError('Las reservas están deshabilitadas.')
    if not get_available_tables(date, time, duration, party_size, public=public).filter(pk=table.pk).exists():
        raise ValidationError('La mesa ya no está disponible para ese horario y número de personas.')
    if not isinstance(customer_name, str) or not isinstance(customer_phone, str):
        raise ValidationError('Ingresa nombre y teléfono como texto.')
    name = customer_name.strip()
    phone = re.sub(r'[\s()\-]', '', customer_phone)
    if not name or not re.fullmatch(r'\+[1-9][0-9]{7,14}', phone):
        raise ValidationError('Ingresa nombre y teléfono internacional, por ejemplo +502 5555 5555.')
    return Reservation(table=table, area_id=table.area_id, customer_name=name, customer_phone=phone,
                       reservation_date=date, start_time=time, starts_at=start, ends_at=end,
                       duration_minutes=duration, party_size=party_size)


@sync_atomic('cloud')
@transaction.atomic
def create_public_reservation_request(table, customer_name, customer_phone, date, time, party_size):
    lock_operation_gate()
    config = get_settings()
    row = _new(table, customer_name, customer_phone, date, time, party_size, config)
    row.hold_expires_at = timezone.now() + timedelta(minutes=config.public_hold_minutes)
    save(row)
    log(row, 'requested')
    return row


@sync_atomic('cloud')
@transaction.atomic
def create_manual_reservation(table, customer_name, customer_phone, date, time, party_size, user, *, duration=None, **terms):
    require(user, 'create_reservation')
    lock_operation_gate()
    config = get_settings()
    row = _new(table, customer_name, customer_phone, date, time, party_size, config, duration, public=False)
    row.created_by = user
    payment_terms(row, config, **terms)
    _approve(row, user, config)
    log(row, 'created_manually', user)
    return row


def _approve(row, user, config):
    row.approved_by, row.approved_at = user, timezone.now()
    row.status = 'AWAITING_PAYMENT' if row.payment_required else 'CONFIRMED'
    row.hold_expires_at = None
    row.payment_expires_at = timezone.now() + timedelta(minutes=config.payment_window_minutes) if row.payment_required else None
    save(row)
    log(row, 'approved', user, amount=str(row.payment_amount), application=row.payment_application,
        percentage_base=str(row.payment_base_amount))


@sync_atomic('cloud')
@transaction.atomic
def approve_reservation(reservation, user, **terms):
    require(user, 'approve_reservation')
    row = locked(reservation)
    check_state(row, 'PENDING_REVIEW')
    # Configuración de mesa puede haber cambiado desde la solicitud.
    if not row.table.is_active or row.table.operational_status != 'ACTIVE' or not row.table.area.is_active:
        raise ValidationError('La mesa debe estar activa y en servicio.')
    config = get_settings()
    payment_terms(row, config, **terms)
    _approve(row, user, config)
    return row


@sync_atomic('cloud')
@transaction.atomic
def reject_reservation(reservation, user, reason):
    require(user, 'reject_reservation')
    row = locked(reservation)
    check_state(row, 'PENDING_REVIEW')
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('Indica el motivo del rechazo.')
    row.status, row.rejection_reason = 'REJECTED', str(reason).strip()
    row.rejected_by, row.rejected_at = user, timezone.now()
    save(row)
    log(row, 'rejected', user, reason=row.rejection_reason)
    return row


def validate_proof(file):
    if not file:
        return
    if file.size > 5 * 1024 * 1024:
        raise ValidationError('El comprobante no debe superar 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            image = Image.open(file)
            if image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise ValueError
            extension={'JPEG':'.jpg','PNG':'.png','WEBP':'.webp'}[image.format]
            image.verify()
            file.seek(0)
            decoded = Image.open(file)
            decoded.load()
        file.seek(0)
        file.name='proof'+extension
    except Exception:
        raise ValidationError('Sube una imagen JPEG, PNG o WebP válida.')


@sync_atomic('cloud')
@transaction.atomic
def submit_reservation_payment(reservation, amount, reference, proof_image=None):
    row = locked(reservation)
    check_state(row, 'AWAITING_PAYMENT')
    if not isinstance(reference, str):
        raise ValidationError('La referencia de transferencia es obligatoria.')
    reference = reference.strip()
    if not reference:
        raise ValidationError('La referencia de transferencia es obligatoria.')
    amount = money(amount)
    if amount != row.payment_amount:
        raise ValidationError('El monto debe coincidir con el anticipo requerido.')
    if not row.created_by_id and not proof_image:
        raise ValidationError('Adjunta el comprobante de la transferencia.')
    validate_proof(proof_image)
    payment = ReservationPayment(reservation=row, amount=amount, reference=reference, proof_image=proof_image or '')
    # Validar antes de escribir el archivo; retirar archivo si falla la escritura SQL.
    payment.full_clean()
    try:
        save_tracked(payment)
        row.status = 'PAYMENT_REVIEW'
        save(row)
        log(row, 'payment_submitted', amount=str(amount))
    except Exception:
        if payment.proof_image and payment.proof_image._committed:
            payment.proof_image.delete(save=False)
        raise
    return payment


@sync_atomic('cloud')
@transaction.atomic
def confirm_reservation_payment(payment, user):
    require(user, 'verify_reservation_payment')
    row = locked(payment.reservation)
    check_state(row, 'PAYMENT_REVIEW')
    payment = ReservationPayment.objects.select_for_update().get(pk=payment.pk, reservation=row)
    if payment.status != 'PENDING' or payment.amount != row.payment_amount:
        raise ValidationError('El pago ya fue revisado o no coincide con el anticipo.')
    payment.status, payment.reviewed_by, payment.reviewed_at = 'CONFIRMED', user, timezone.now()
    save(payment)
    row.status = 'CONFIRMED'
    save(row)
    log(row, 'payment_confirmed', user, amount=str(payment.amount))
    return row


@sync_atomic('cloud')
@transaction.atomic
def reject_reservation_payment(payment, user, reason):
    require(user, 'reject_reservation_payment')
    row = locked(payment.reservation)
    check_state(row, 'PAYMENT_REVIEW')
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('Indica el motivo del rechazo.')
    payment = ReservationPayment.objects.select_for_update().get(pk=payment.pk, reservation=row)
    if payment.status != 'PENDING':
        raise ValidationError('El pago ya fue revisado.')
    payment.status, payment.reviewed_by, payment.reviewed_at = 'REJECTED', user, timezone.now()
    payment.rejection_reason = str(reason).strip()
    save(payment)
    row.status, row.rejection_reason = 'REJECTED', payment.rejection_reason
    row.rejected_by, row.rejected_at = user, timezone.now()
    save(row)
    log(row, 'payment_rejected', user, reason=payment.rejection_reason)
    return row


@sync_atomic('cloud')
@transaction.atomic
def cancel_reservation(reservation, user, reason=''):
    require(user, 'cancel_reservation')
    row = locked(reservation)
    check_state(row, 'PENDING_REVIEW', 'AWAITING_PAYMENT', 'PAYMENT_REVIEW', 'CONFIRMED')
    if not isinstance(reason, str):
        raise ValidationError('El motivo debe ser texto.')
    if (row.status in ('CONFIRMED', 'PAYMENT_REVIEW') or row.payment_required) and not str(reason).strip():
        raise ValidationError('Indica el motivo de la cancelación.')
    row.status, row.cancellation_reason = 'CANCELLED', str(reason).strip()
    row.cancelled_by, row.cancelled_at = user, timezone.now()
    save(row)
    log(row, 'cancelled', user, reason=row.cancellation_reason)
    return row


@sync_atomic('cloud')
@transaction.atomic
def mark_reservation_no_show(reservation, user, reason=''):
    require(user, 'mark_reservation_no_show')
    row = locked(reservation)
    check_state(row, 'CONFIRMED')
    if row.starts_at > timezone.now():
        raise ValidationError('Todavía no ha llegado la hora de la reserva.')
    if not isinstance(reason, str):
        raise ValidationError('El motivo debe ser texto.')
    row.status, row.no_show_reason = 'NO_SHOW', reason.strip()
    row.no_show_at, row.no_show_by = timezone.now(), user
    save(row)
    log(row, 'no_show', user, reason=row.no_show_reason)
    return row


@sync_atomic('cloud', action='arrival')
@transaction.atomic
def confirm_reservation_arrival(reservation, user, responsible_waiter):
    require(user, 'confirm_reservation_arrival')
    day = lock_open_day()
    row = locked(reservation)
    check_state(row, 'CONFIRMED')
    if not responsible_waiter:
        raise ValidationError('Selecciona un mesero responsable.')
    responsible_waiter.refresh_from_db()
    if not responsible_waiter.is_active or responsible_waiter.role != 'MESERO':
        raise ValidationError('Selecciona un mesero activo.')
    # Llegadas anticipadas/tardías explícitas son posibles, sin desplazar otra reserva vigente.
    now = timezone.now()
    if blocking_reservations(now).exclude(pk=row.pk).filter(table=row.table, starts_at__lte=now, ends_at__gt=now).exists():
        raise ValidationError('La mesa está retenida para otra reserva en este momento.')
    from apps.orders.services import _create_table_order
    order = _create_table_order(row.table, user, day=day, responsible=responsible_waiter)
    row.order, row.status = order, 'ARRIVED'
    row.arrival_confirmed_at, row.arrival_confirmed_by = now, user
    save(row)
    if row.payment_required:
        payment = ReservationPayment.objects.select_for_update().filter(reservation=row, status='CONFIRMED').first()
        if not payment or payment.amount != row.payment_amount:
            raise ValidationError('Falta el anticipo confirmado de esta reserva.')
        if row.payment_application == 'CREDIT':
            credit = track(ReservationCredit.objects.create(order=order, payment=payment, amount=payment.amount, created_by=user))
            log(row, 'credit_created', user, credit_id=credit.pk, order_id=order.pk, amount=str(credit.amount))
    log(row, 'arrived', user, order_id=order.pk, responsible_waiter_id=responsible_waiter.pk)
    from apps.sync.services import capture_arrival
    capture_arrival(row)
    return row


@sync_atomic('cloud')
@transaction.atomic
def expire_reservations(status):
    if status not in ('PENDING_REVIEW', 'AWAITING_PAYMENT'):
        raise ValueError('Estado no expirable')
    lock_operation_gate()
    field = 'hold_expires_at' if status == 'PENDING_REVIEW' else 'payment_expires_at'
    count = 0
    for row in Reservation.objects.select_for_update().filter(status=status, **{field + '__lte': timezone.now()}):
        row.status = 'EXPIRED'
        save(row)
        log(row, 'expired', previous_status=status)
        count += 1
    return count


@sync_atomic('cloud')
@transaction.atomic
def configure_reservations(user, **values):
    require(user, 'configure_reservations')
    lock_operation_gate()
    config = get_settings()
    allowed = {field.name for field in ReservationSettings._meta.fields} - {'id'}
    if set(values) - allowed:
        raise ValidationError('Configuración desconocida.')
    for field, value in values.items():
        setattr(config, field, value)
    save(config)
    AuditLog.objects.create(user=user, action='reservations.configured', entity='reservations.settings', entity_id='1',
                           data={k: str(v) for k, v in values.items()})
    return config
