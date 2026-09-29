from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone

from apps.tables.models import VenueTable
from .models import Reservation, ReservationSettings


def get_settings():
    return ReservationSettings.objects.filter(pk=1).first() or ReservationSettings()


def interval(date, time, duration):
    if type(duration) is not int or not 1 <= duration <= 1440:
        raise ValidationError('La duración debe estar entre 1 y 1440 minutos.')
    start = timezone.make_aware(datetime.combine(date, time))
    return start, start + timedelta(minutes=duration)


def blocking_reservations(now=None):
    now = now or timezone.now()
    return Reservation.objects.filter(
        Q(status__in=['CONFIRMED', 'PAYMENT_REVIEW']) |
        Q(status='ARRIVED', order__status__in=['OPEN', 'PARTIALLY_PAID', 'PAYMENT_PENDING']) |
        Q(status='PENDING_REVIEW', hold_expires_at__gt=now) |
        Q(status='AWAITING_PAYMENT', payment_expires_at__gt=now))


def get_available_tables(date, time, duration, party_size=None, area=None, *, public=True):
    start, end = interval(date, time, duration)
    tables = VenueTable.objects.filter(is_active=True, operational_status='ACTIVE', area__is_active=True)
    if public:
        if not get_settings().reservations_enabled:
            return tables.none()
        tables = tables.filter(reservable_web=True)
    if party_size is not None:
        if type(party_size) is not int or party_size <= 0:
            raise ValidationError('Indica un número de personas mayor que cero.')
        tables = tables.filter(capacity__gte=party_size)
    if area is not None:
        tables = tables.filter(area=area)
    busy = blocking_reservations().filter(starts_at__lt=end, ends_at__gt=start).values('table_id')
    tables = tables.exclude(pk__in=busy)
    # Una cuenta abierta no tiene fin estimado: impide reservar el intervalo en curso.
    if start <= timezone.now() < end:
        tables = tables.exclude(order_links__released_at__isnull=True, order_links__order__status__in=['OPEN', 'PARTIALLY_PAID', 'PAYMENT_PENDING'])
    return tables.select_related('area').order_by('area__sort_order', 'sort_order', 'name').distinct()


def current_reserved_tables(now=None):
    now = now or timezone.now()
    return Reservation.objects.filter(status='CONFIRMED', starts_at__lte=now, ends_at__gt=now)


def ensure_not_reserved(table):
    if current_reserved_tables().filter(table=table).exists():
        raise ValidationError('La mesa está reservada. Gerencia debe confirmar la llegada desde Reservas.')
