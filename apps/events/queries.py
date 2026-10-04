import hashlib
import json
from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from .models import Event, EventPurchase, EventPurchaseItem, EventTicket, EventSettings, EventTableReservation

LIVE_STATUSES = ('PUBLISHED', 'RESCHEDULED')


def get_settings():
    return EventSettings.objects.filter(pk=1).first() or EventSettings()


def active_purchases(event, now=None):
    now = now or timezone.now()
    return EventPurchase.objects.filter(event=event).filter(Q(status__in=['PAYMENT_REVIEW', 'CONFIRMED']) |
        Q(status='PENDING_PAYMENT', hold_expires_at__gt=now, payment_expires_at__gt=now))


def pending_purchases(event, now=None):
    return active_purchases(event, now).exclude(status='CONFIRMED')


def type_committed(ticket_type, now=None):
    holds = EventPurchaseItem.objects.filter(ticket_type=ticket_type, purchase__in=pending_purchases(ticket_type.event, now)).aggregate(n=Sum('quantity'))['n'] or 0
    issued = EventTicket.objects.filter(ticket_type=ticket_type, table_reservation__isnull=True).exclude(status='CANCELLED').count()
    return holds + issued


def table_available(config, now=None):
    return config.enabled and not EventTableReservation.objects.filter(table_configuration=config, purchase__in=active_purchases(config.event, now)).exists()


def get_event_capacity_summary(event, now=None):
    pending = pending_purchases(event, now)
    held = (EventPurchaseItem.objects.filter(purchase__in=pending).aggregate(n=Sum('quantity'))['n'] or 0)
    held += (EventTableReservation.objects.filter(purchase__in=pending).aggregate(n=Sum('table_configuration__capacity_snapshot'))['n'] or 0)
    tickets = event.tickets.exclude(status='CANCELLED')
    sold = tickets.filter(purchase__isnull=False, table_reservation__isnull=True).count()
    courtesy = tickets.filter(purchase__isnull=True).count()
    tables = tickets.filter(table_reservation__isnull=False).count()
    return dict(maximum_capacity=event.maximum_capacity, held=held, sold_individual=sold, courtesy=courtesy,
        table_accesses=tables, used_at_entrance=tickets.filter(status='USED').count(),
        remaining=event.maximum_capacity-held-sold-courtesy-tables)


def configuration_summary(event):
    # Desactivar no libera compromisos vigentes de un tipo.
    individual = sum(max(t.capacity if t.is_active else 0, type_committed(t)) for t in event.ticket_types.all())
    # Una mesa deshabilitada sin reservas no ocupa pool.
    tables = sum(c.capacity_snapshot for c in event.table_configurations.all() if c.enabled or c.reservations.filter(purchase__in=active_purchases(event)).exists())
    return dict(individual=individual, tables=tables, total=individual+tables)


def ticket_type_rows(event):
    now = timezone.now()
    remaining = get_event_capacity_summary(event, now)['remaining']
    rows = []
    for row in event.ticket_types.all():
        row.committed = type_committed(row, now)
        row.available = max(0, min(row.capacity-row.committed, remaining)) if row.is_active else 0
        row.sold = event.tickets.filter(ticket_type=row, table_reservation__isnull=True).exclude(status='CANCELLED').count()
        row.sellable = (event.status in LIVE_STATUSES and event.ticket_sales_enabled and event.ends_at > now and row.is_active
            and not row.is_courtesy_type and row.price > 0 and row.sale_starts_at <= now <= row.sale_ends_at and row.available > 0)
        row.percent = min(100, round(100*row.committed/row.capacity)) if row.capacity else 0
        rows.append(row)
    return rows


def table_rows(event):
    rows = list(event.table_configurations.select_related('table__area', 'ticket_type').order_by('table__area__sort_order', 'table__area_id', 'table__level', 'table__sort_order', 'table__name'))
    for row in rows:
        row.available = table_available(row)
    return rows


@transaction.atomic
def build_event_access_snapshot(event):
    event = Event.objects.select_for_update().get(pk=event.pk)
    rows = [{'token_hash': hashlib.sha256(t.qr_token.encode()).hexdigest(), 'status': t.status,
             'ticket_type': t.ticket_type.name} for t in event.tickets.select_related('ticket_type').order_by('pk')]
    content = dict(schema_version=1, event_id=event.pk, event=event.name, event_status=event.status, tickets=rows)
    checksum = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest()
    return {**content, 'generated_at': timezone.now().isoformat(), 'version': checksum, 'checksum': checksum}
