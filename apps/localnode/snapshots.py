"""Manual signed transport of the existing schema-1 access snapshot. No network IO."""
import hashlib
import hmac
import json
import re
from datetime import timedelta
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.events.queries import build_event_access_snapshot
from .models import LocalNodeIdentity, LocalEventAccessSnapshot, LocalAccessTicket

CONTENT_KEYS = {'schema_version', 'event_id', 'event', 'event_status', 'tickets'}
TRANSPORT_KEYS = CONTENT_KEYS | {'generated_at', 'version', 'checksum', 'source', 'signature'}
HEX = re.compile(r'[a-f0-9]{64}')
MAX_SNAPSHOT_BYTES = 20 * 1024 * 1024


def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def signing_key():
    key = settings.ACCESS_SNAPSHOT_SIGNING_KEY
    if len(key.encode()) < 32:
        raise ValidationError('Configura ACCESS_SNAPSHOT_SIGNING_KEY con al menos 32 bytes aleatorios.')
    return key.encode()


def signed_snapshot(event):
    if settings.DEPLOYMENT_MODE == 'local_node':
        raise ValidationError('Exporta desde la base fuente, no desde el nodo local.')
    data = {**build_event_access_snapshot(event), 'source': settings.ACCESS_SNAPSHOT_SOURCE}
    data['signature'] = hmac.new(signing_key(), canonical(data), hashlib.sha256).hexdigest()
    return data


def validate_snapshot(data):
    fail = ValidationError('Snapshot inválido, incompatible o no autenticado.')
    if not isinstance(data, dict) or set(data) != TRANSPORT_KEYS:
        raise fail
    if not isinstance(data['signature'], str) or not HEX.fullmatch(data['signature']):
        raise fail
    expected = hmac.new(signing_key(), canonical({k:v for k,v in data.items() if k != 'signature'}), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, data['signature']):
        raise fail
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        raise fail
    if type(data['event_id']) is not int or not 0 < data['event_id'] <= 9223372036854775807:
        raise fail
    if data['source'] != settings.ACCESS_SNAPSHOT_SOURCE or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', data['source']):
        raise fail
    if not isinstance(data['event'], str) or not 1 <= len(data['event']) <= 140:
        raise fail
    if data['event_status'] not in ('DRAFT','PUBLISHED','RESCHEDULED','FINISHED','CANCELLED'):
        raise fail
    try:
        stamp = parse_datetime(data['generated_at'])
        if stamp is None or timezone.is_naive(stamp) or stamp > timezone.now() + timedelta(minutes=5):
            raise fail
    except (TypeError, ValueError):
        raise fail
    checksum = hashlib.sha256(canonical({key:data[key] for key in CONTENT_KEYS})).hexdigest()
    if data['version'] != checksum or data['checksum'] != checksum:
        raise fail
    if not isinstance(data['tickets'], list) or len(data['tickets']) > 100000:
        raise fail
    seen = set()
    for row in data['tickets']:
        if not isinstance(row, dict) or set(row) != {'token_hash','status','ticket_type'}:
            raise fail
        digest = row['token_hash']
        if not isinstance(digest, str) or not HEX.fullmatch(digest) or digest in seen:
            raise fail
        if row['status'] not in ('VALID','USED','CANCELLED') or not isinstance(row['ticket_type'], str) or not 1 <= len(row['ticket_type']) <= 100:
            raise fail
        seen.add(digest)
    return stamp


def require_local():
    if settings.DEPLOYMENT_MODE != 'local_node':
        raise ValidationError('Esta operación requiere DEPLOYMENT_MODE=local_node.')


@transaction.atomic
def import_snapshot(data):
    require_local()
    stamp = validate_snapshot(data)
    # Serializes imports including the first snapshot, without locking scans of unrelated tickets.
    if not LocalNodeIdentity.objects.select_for_update().filter(pk=1).exists():
        raise ValidationError('Inicializa el nodo antes de importar.')
    snapshot = LocalEventAccessSnapshot.objects.filter(source=data['source'], event_public_identifier=str(data['event_id'])).first()
    if snapshot:
        if stamp < snapshot.generated_at:
            raise ValidationError('Snapshot anterior al último importado. Se conservó la versión actual.')
        if snapshot.version == data['version']:
            # Refresh replay watermark without reopening any ticket or changing the content version.
            if stamp > snapshot.generated_at:
                snapshot.generated_at = stamp
                snapshot.save(update_fields=['generated_at','imported_at'])
            return snapshot, False
        if stamp == snapshot.generated_at:
            raise ValidationError('Dos versiones distintas con la misma fecha de generación.')
    else:
        snapshot = LocalEventAccessSnapshot(source=data['source'], event_public_identifier=str(data['event_id']))
    for field, value in dict(event_name=data['event'], event_status=data['event_status'], version=data['version'], checksum=data['checksum'], generated_at=stamp, is_active=True).items():
        setattr(snapshot, field, value)
    snapshot.save()
    digests = []
    for row in data['tickets']:
        digest = row['token_hash']; digests.append(digest)
        ticket = LocalAccessTicket.objects.select_for_update().filter(token_digest=digest).first()
        if ticket and ticket.snapshot_id != snapshot.pk:
            raise ValidationError('Un digest no puede pertenecer a dos eventos distintos.')
        ticket = ticket or LocalAccessTicket(snapshot=snapshot, token_digest=digest)
        incoming = 'CANCELLED' if data['event_status'] == 'CANCELLED' else row['status']
        if incoming == 'CANCELLED' or ticket.status == 'CANCELLED':
            ticket.status = 'CANCELLED'
        elif ticket.used_at or ticket.status == 'USED' or incoming == 'USED':
            ticket.status = 'USED'
        else:
            ticket.status = 'VALID'
        ticket.ticket_type_name = row['ticket_type']
        ticket.save()
    # Snapshots are complete sets. Omitted access is revoked, never silently left valid.
    snapshot.tickets.exclude(token_digest__in=digests).update(status='CANCELLED', updated_at=timezone.now())
    return snapshot, True
