import json
from pathlib import Path
from django.conf import settings
from django.db import connection, DatabaseError
from .models import LocalNodeIdentity, LocalEventAccessSnapshot
from apps.printing.models import Printer


def database_ready():
    try:
        if connection.vendor != 'postgresql':
            return False
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            return cursor.fetchone() == (1,)
    except DatabaseError:
        return False


def collected_static_ready():
    root = Path(settings.STATIC_ROOT)
    try:
        manifest = json.loads((root / 'staticfiles.json').read_text(encoding='utf-8'))['paths']
        return all((root / manifest[name]).is_file() for name in (
            'css/operations/base.css', 'js/events/scanner.js',
            'vendor/qr-scanner/qr-scanner.min.js', 'vendor/qr-scanner/qr-scanner-worker.min.js'))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def inspect_node():
    checks = [('Modo local', settings.DEPLOYMENT_MODE == 'local_node'),
              ('DEBUG desactivado', not settings.DEBUG), ('PostgreSQL disponible', database_ready()),
              ('Hosts explícitos', bool(settings.ALLOWED_HOSTS) and not any('*' in h for h in settings.ALLOWED_HOSTS)),
              ('CSRF explícito', bool(settings.CSRF_TRUSTED_ORIGINS) and not any('*' in h for h in settings.CSRF_TRUSTED_ORIGINS)),
              ('Clave de snapshots configurada', len(settings.ACCESS_SNAPSHOT_SIGNING_KEY.encode()) >= 32),
              ('Static recolectado', collected_static_ready()),
              ('Impresión de red', settings.PRINTER_BACKEND == 'network')]
    from apps.core.ops.files import disk_free
    free=disk_free(settings.MEDIA_ROOT)/(1024**3)
    checks.append(('Espacio libre suficiente',free>=settings.MIN_FREE_DISK_GB))
    warnings = []
    if free<settings.MIN_FREE_DISK_GB:warnings.append('Espacio libre por debajo del umbral configurado.')
    if checks[2][1]:
        try:
            checks.append(('Identidad inicializada', LocalNodeIdentity.objects.filter(pk=1).exists()))
            configured = Printer.objects.filter(is_active=True).exclude(host='').count()
            checks.append((f'Impresoras registradas: {Printer.objects.count()} / configuradas activas: {configured}', True))
            checks.append((f'Snapshots QR activos: {LocalEventAccessSnapshot.objects.filter(is_active=True).count()}', True))
            if not configured: warnings.append('No hay impresoras de red activas configuradas.')
            if not LocalEventAccessSnapshot.objects.filter(is_active=True).exists():
                warnings.append('Sin snapshots QR importados: acceso offline aún sin entradas.')
        except DatabaseError:
            checks.append(('Migraciones locales aplicadas', False))
    if settings.PRINTER_BACKEND == 'debug' and getattr(settings, 'LOCAL_NODE_ALLOW_DEBUG_PRINTER', False):
        checks = [(label, True if label == 'Impresión de red' else value) for label,value in checks]
        warnings.append('Impresión debug autorizada solo para simulación.')
    if not getattr(settings, 'LOCAL_NODE_HTTPS', True):
        warnings.append('HTTP de simulación: cámara móvil LAN y cookies Secure requieren HTTPS real.')
    return checks, warnings
