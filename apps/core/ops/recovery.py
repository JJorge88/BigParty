import json
from pathlib import Path
from datetime import datetime, timezone
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.management.base import CommandError
from .files import private_root, atomic_json


def marker():
    return Path(settings.OPERATIONS_STATE_ROOT) / 'recovery.json'


def status():
    path = marker()
    try:
        if not path.exists():return {'active':bool(settings.RECOVERY_MODE),'reason':'Environment flag' if settings.RECOVERY_MODE else ''}
        data = json.loads(path.read_text())
        if not isinstance(data,dict) or type(data.get('active')) is not bool:raise ValueError
        return {**data,'active':settings.RECOVERY_MODE or data['active']}
    except (OSError,ValueError):return {'active':True,'reason':'Invalid recovery state; operator review required'}


def require_operational():
    if status()['active']:raise PermissionDenied('Modo recuperación: operación suspendida hasta completar la revisión.')


def enter(reason='Operator requested recovery', target_database=None):
    private_root(settings.OPERATIONS_STATE_ROOT)
    atomic_json(marker(),{'active':True,'reason':reason[:200], 'entered_at':datetime.now(timezone.utc).isoformat(),
                         'target_database':target_database or str(settings.DATABASES['default']['NAME'])})


def complete(confirm=False, sync_reviewed=False):
    if not confirm or not sync_reviewed:raise CommandError('Requiere --confirm --sync-reviewed después de comparar el estado con Cloud.')
    if settings.RECOVERY_MODE:raise CommandError('Conserva el marcador persistente y cambia RECOVERY_MODE=false antes de completar la recuperación.')
    current = status()
    if current.get('target_database',str(settings.DATABASES['default']['NAME'])) != str(settings.DATABASES['default']['NAME']):
        raise CommandError('RECOVERY_DATABASE_MISMATCH')
    from .integrity import restored_report
    report = restored_report()
    if report['errors']:raise CommandError('RECOVERY_CHECKS_FAILED: ejecuta verify_restored_system.')
    private_root(settings.OPERATIONS_STATE_ROOT)
    atomic_json(marker(),{'active':False,'completed_at':datetime.now(timezone.utc).isoformat(),'sync_reviewed':True})
