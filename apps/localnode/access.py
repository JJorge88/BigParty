from apps.sync.services import sync_atomic, track, save_tracked
import hashlib
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from apps.events.access import eligible
from .models import LocalNodeIdentity, LocalAccessTicket, LocalAccessScan
from .snapshots import require_local


@sync_atomic('local')
@transaction.atomic
def validate_and_use_local_ticket(token, guard_user):
    require_local()
    if not eligible(guard_user):
        raise PermissionDenied('Acceso no permitido.')
    node = LocalNodeIdentity.objects.filter(pk=1).first()
    if not node:
        raise ValidationError('Nodo no inicializado.')
    raw = token if isinstance(token, str) and len(token) <= 2048 else ''
    digest = hashlib.sha256(raw.encode()).hexdigest()
    ticket = LocalAccessTicket.objects.select_for_update(of=('self',)).select_related('snapshot').filter(token_digest=digest).first()
    result, label, data = 'INVALID', 'No disponible localmente', {}
    if ticket and ticket.snapshot.is_active:
        data = {'event':ticket.snapshot.event_name, 'ticket_type':ticket.ticket_type_name}
        if ticket.status == 'CANCELLED' or ticket.snapshot.event_status == 'CANCELLED':
            result, label = 'CANCELLED', 'Cancelada'
        elif ticket.status == 'USED':
            result, label = 'USED', 'Ya utilizada'
            if ticket.used_at: data['used_at'] = ticket.used_at.isoformat()
        elif ticket.snapshot.event_status in ('PUBLISHED','RESCHEDULED'):
            ticket.status, ticket.used_at = 'USED', timezone.now()
            save_tracked(ticket, update_fields=['status','used_at','updated_at'])
            result, label = 'VALID', 'Válida'
            data['used_at'] = ticket.used_at.isoformat()
    scan = track(LocalAccessScan.objects.create(node=node, token_digest=digest, result=result, scanned_by=guard_user,
        event_identifier=f'{ticket.snapshot.source}:{ticket.snapshot.event_public_identifier}' if ticket else '',
        snapshot_version=ticket.snapshot.version if ticket else ''))
    from apps.sync.services import capture_scan
    capture_scan(scan)
    return {**data, 'result':result, 'label':label}
