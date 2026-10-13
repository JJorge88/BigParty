import hashlib
import json
import time
from pathlib import Path
from django.conf import settings
from .files import atomic_json
from .locking import file_lock


def limit_for(path):
    if path.startswith('/api/sync/v1/'):return 'sync',settings.RATE_LIMIT_SYNC
    if path == '/ingresar/':return 'login-router',settings.RATE_LIMIT_LOGIN
    # Cada puerta conserva su propia protección. Un PIN equivocado en tablets o
    # caja nunca debe impedir que el gerente entre desde la misma conexión.
    login_scopes = {
        '/gerencia/acceso/': 'management-login',
        '/admin/login/': 'django-admin-login',
        '/acceso/ingresar/': 'unified-login',
        '/caja/acceso/': 'cash-login',
        '/operacion/acceso/': 'tablet-login',
        '/tablet/': 'tablet-router',
    }
    if path in login_scopes:
        return login_scopes[path],settings.RATE_LIMIT_LOGIN
    if path.startswith(('/eventos/compra/','/reservas/r/')):return 'upload',settings.RATE_LIMIT_UPLOAD
    if path.startswith('/reservas/') or path.startswith('/eventos/'):
        return 'public',settings.RATE_LIMIT_PUBLIC
    return None


def accept(scope, identity, limit):
    # No raw IP, phone, username or session token at rest. Counters are shared by processes.
    key=hashlib.sha256((scope+'\0'+identity).encode()).hexdigest()
    folder=Path(settings.OPERATIONS_STATE_ROOT)/'rate-limits'
    path=folder/(key+'.json');now=time.time();window=settings.RATE_LIMIT_WINDOW_SECONDS
    with file_lock(folder/(key+'.lock')):
        try:value=json.loads(path.read_text())
        except FileNotFoundError:value={'start':now,'count':0}
        if now-value['start']>=window:value={'start':now,'count':0}
        if value['count']>=limit:return False,max(1,int(window-(now-value['start'])))
        value['count']+=1;atomic_json(path,value)
    return True,0
