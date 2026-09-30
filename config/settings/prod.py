"""Separación mínima para producción; el despliegue queda fuera de la Fase 0."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEPLOYMENT_MODE = os.environ.get('DEPLOYMENT_MODE', 'cloud')
DEBUG = False
RATE_LIMIT_ENABLED = env_bool('RATE_LIMIT_ENABLED', True)
SECURITY_HEADERS_ENABLED = env_bool('SECURITY_HEADERS_ENABLED', True)
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Producción requiere DJANGO_ALLOWED_HOSTS explícitos.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

if SYNC_ENABLED:
    if len(SYNC_SHARED_SECRET.encode()) < 32 or not APP_VERSION or len(ACCESS_SNAPSHOT_SIGNING_KEY.encode()) < 32:
        raise ImproperlyConfigured('Sync requiere claves independientes y APP_VERSION configurados.')
    SYNC_LOG_ROOT = Path(os.environ.get('SYNC_LOG_ROOT', str(BASE_DIR / 'var' / 'log')))
    SYNC_LOG_ROOT.mkdir(parents=True, exist_ok=True)
    LOGGING = {
        'version':1,'disable_existing_loggers':False,
        'filters':{'sync_safe':{'()':'apps.sync.logging.SyncSafeFilter'}},
        'formatters':{'sync':{'format':'{asctime} {levelname} {message}','style':'{'}},
        'handlers':{'sync':{'class':'logging.handlers.RotatingFileHandler','filename':str(SYNC_LOG_ROOT/'sync.log'),
            'maxBytes':5*1024*1024,'backupCount':5,'encoding':'utf-8','filters':['sync_safe'],'formatter':'sync'}},
        'loggers':{'apps.sync':{'handlers':['sync'],'level':'INFO','propagate':False}},
    }

# Production defaults; local_node overrides HSTS/HTTPS for its explicit LAN profile.
if len(SECRET_KEY) < 50 or len(set(SECRET_KEY)) < 5 or SECRET_KEY.startswith('django-insecure-'):
    raise ImproperlyConfigured('DJANGO_SECRET_KEY debe ser aleatoria y tener al menos 50 caracteres.')
if len(ACCESS_SNAPSHOT_SIGNING_KEY.encode()) < 32:
    raise ImproperlyConfigured('Configura ACCESS_SNAPSHOT_SIGNING_KEY de al menos 32 bytes.')
if len(SYNC_SHARED_SECRET.encode()) < 32 or len({SECRET_KEY, SYNC_SHARED_SECRET, ACCESS_SNAPSHOT_SIGNING_KEY}) != 3:
    raise ImproperlyConfigured('SYNC_SHARED_SECRET requiere al menos 32 bytes y una clave independiente.')
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_SSL_REDIRECT = env_bool('SECURE_SSL_REDIRECT', True)
SECURE_REDIRECT_EXEMPT = [r'^healthz/$', r'^readyz/$']
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = 'same-origin'
SECURE_HSTS_SECONDS = int(os.environ.get('SECURE_HSTS_SECONDS', '3600'))
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
# Domain/subdomain inventory and preload consent are deferred to physical deployment.
SILENCED_SYSTEM_CHECKS = ['security.W005', 'security.W021']
X_FRAME_OPTIONS = 'DENY'
SECURE_PROXY_SSL_HEADER = None  # Trusted loopback WSGI proxy owns scheme/REMOTE_ADDR.
MEDIA_ROOT = Path(os.environ.get('PUBLIC_MEDIA_ROOT', str(MEDIA_ROOT)))
RESERVATION_PROOF_ROOT = Path(os.environ.get('RESERVATION_PROOF_ROOT', str(RESERVATION_PROOF_ROOT)))
EVENT_PROOF_ROOT = Path(os.environ.get('EVENT_PROOF_ROOT', str(EVENT_PROOF_ROOT)))
for private in (RESERVATION_PROOF_ROOT, EVENT_PROOF_ROOT):
    if private.resolve() == MEDIA_ROOT.resolve() or private.resolve().is_relative_to(MEDIA_ROOT.resolve()):
        raise ImproperlyConfigured('Comprobantes privados deben estar fuera de media pública.')
OPERATIONS_STATE_ROOT = Path(required_env('OPERATIONS_STATE_ROOT'))
def validate_operations_state(*sources):
    path = OPERATIONS_STATE_ROOT.resolve()
    if not OPERATIONS_STATE_ROOT.is_absolute():
        raise ImproperlyConfigured('OPERATIONS_STATE_ROOT debe ser una carpeta privada absoluta persistente.')
    for source in (sources or (BASE_DIR, MEDIA_ROOT, STATIC_ROOT, RESERVATION_PROOF_ROOT, EVENT_PROOF_ROOT)):
        source = Path(source).resolve()
        if path == source or path.is_relative_to(source) or source.is_relative_to(path):
            raise ImproperlyConfigured('OPERATIONS_STATE_ROOT debe estar separada del proyecto y media/static.')
validate_operations_state()
if SYNC_SHARED_SECRET_PREVIOUS:
    from datetime import datetime, timezone
    try:
        deadline = datetime.fromisoformat(SYNC_SECRET_PREVIOUS_UNTIL)
        remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
        if len(SYNC_SHARED_SECRET_PREVIOUS.encode()) < 32 or not 0 < remaining <= 86400:
            raise ValueError
    except (ValueError, TypeError):
        raise ImproperlyConfigured('La clave anterior sync requiere ventana explícita vigente, máximo 24 horas.')
SUPPORT_LOG_ROOT = Path(os.environ.get('SUPPORT_LOG_ROOT', str(BASE_DIR / 'var' / 'log')))
SUPPORT_LOG_ROOT.mkdir(parents=True, exist_ok=True)
if 'LOGGING' not in globals():LOGGING = {'version':1, 'disable_existing_loggers':False, 'filters':{}, 'handlers':{}, 'loggers':{}}
LOGGING['filters']['support_safe'] = {'()':'apps.core.ops.logging.SafeSupportFilter'}
LOGGING['handlers']['support'] = {'class':'logging.handlers.RotatingFileHandler','filename':str(SUPPORT_LOG_ROOT/'support.log'), 'maxBytes':5242880,'backupCount':5,'encoding':'utf-8','filters':['support_safe']}
LOGGING['loggers']['apps.hardening'] = {'handlers':['support'],'level':'WARNING','propagate':False}
LOGGING['loggers']['django.request'] = {'handlers':['support'],'level':'ERROR','propagate':False}
