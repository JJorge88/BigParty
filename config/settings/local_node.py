"""Single PostgreSQL LAN node. Caddy terminates HTTPS; Waitress serves loopback."""
from .prod import *  # noqa: F403
from urllib.parse import urlsplit

if DEPLOYMENT_MODE != 'local_node':
    raise ImproperlyConfigured('Selecciona DEPLOYMENT_MODE=local_node para este perfil.')
LOCAL_NODE_NAME = os.environ.get('LOCAL_NODE_NAME', 'BIG PARTY Principal')
LOCAL_NODE_HOSTNAME = required_env('LOCAL_NODE_HOSTNAME')
LOCAL_NODE_BIND_HOST = os.environ.get('LOCAL_NODE_BIND_HOST', '127.0.0.1')
LOCAL_NODE_PORT = int(os.environ.get('LOCAL_NODE_PORT', '8000'))
LOCAL_NODE_HTTPS = env_bool('LOCAL_NODE_HTTPS', True)
LOCAL_NODE_ALLOW_DEBUG_PRINTER = env_bool('LOCAL_NODE_ALLOW_DEBUG_PRINTER', False)
LOCAL_NODE_DB_WAIT_SECONDS = int(os.environ.get('LOCAL_NODE_DB_WAIT_SECONDS', '60'))
if LOCAL_NODE_BIND_HOST not in ('127.0.0.1', '::1') or not 1 <= LOCAL_NODE_PORT <= 65535:
    raise ImproperlyConfigured('Waitress debe escuchar loopback; publica la LAN mediante Caddy.')
if not 0 <= LOCAL_NODE_DB_WAIT_SECONDS <= 60:
    raise ImproperlyConfigured('La espera de PostgreSQL debe estar entre 0 y 60 segundos.')
if DATABASES['default']['HOST'] not in ('127.0.0.1', 'localhost', '::1'):
    raise ImproperlyConfigured('Local Node requiere PostgreSQL en el mismo equipo.')
DATABASES['default']['OPTIONS'] = {'connect_timeout': 3}
DATABASES['default']['CONN_MAX_AGE'] = 60
if not CSRF_TRUSTED_ORIGINS or any('*' in origin or urlsplit(origin).scheme not in ('https','http') or not urlsplit(origin).netloc or urlsplit(origin).path or urlsplit(origin).query or urlsplit(origin).fragment or urlsplit(origin).username for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Configura orígenes CSRF explícitos con esquema y sin comodines/rutas.')
if LOCAL_NODE_HOSTNAME not in ALLOWED_HOSTS or any('*' in host or host.startswith('.') for host in ALLOWED_HOSTS):
    raise ImproperlyConfigured('Incluye LOCAL_NODE_HOSTNAME entre los hosts explícitos.')
if LOCAL_NODE_HTTPS and any(not origin.startswith('https://') for origin in CSRF_TRUSTED_ORIGINS):
    raise ImproperlyConfigured('Los orígenes CSRF deben usar HTTPS en la instalación real.')
PRINTER_BACKEND = os.environ.get('PRINTER_BACKEND', 'network')
if PRINTER_BACKEND != 'network' and not (PRINTER_BACKEND == 'debug' and LOCAL_NODE_ALLOW_DEBUG_PRINTER):
    raise ImproperlyConfigured('Usa PRINTER_BACKEND=network; debug solo con autorización de simulación explícita.')
if len(ACCESS_SNAPSHOT_SIGNING_KEY.encode()) < 32:
    raise ImproperlyConfigured('Configura una clave de snapshots aleatoria de al menos 32 bytes.')
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = LOCAL_NODE_HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = CSRF_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_DOMAIN = CSRF_COOKIE_DOMAIN = None
SECURE_SSL_REDIRECT = LOCAL_NODE_HTTPS
SECURE_REDIRECT_EXEMPT = [r'^healthz/$', r'^readyz/$']
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
# Waitress validates the loopback proxy header and sets wsgi.url_scheme itself.
# Do not trust arbitrary forwarded headers in Django.
SECURE_PROXY_SSL_HEADER = None
MIDDLEWARE.insert(1, 'whitenoise.middleware.WhiteNoiseMiddleware')
STATIC_ROOT = Path(os.environ.get('LOCAL_STATIC_ROOT', str(BASE_DIR / 'staticfiles')))
STORAGES = {'default': {'BACKEND':'django.core.files.storage.FileSystemStorage'},
            'staticfiles': {'BACKEND':'whitenoise.storage.CompressedManifestStaticFilesStorage'}}
WHITENOISE_AUTOREFRESH = False
WHITENOISE_USE_FINDERS = False
MEDIA_ROOT = Path(required_env('LOCAL_MEDIA_ROOT'))
LOCAL_PRIVATE_ROOT = Path(required_env('LOCAL_PRIVATE_ROOT'))
if not MEDIA_ROOT.is_absolute() or not LOCAL_PRIVATE_ROOT.is_absolute() or MEDIA_ROOT == LOCAL_PRIVATE_ROOT or MEDIA_ROOT in LOCAL_PRIVATE_ROOT.parents:
    raise ImproperlyConfigured('Media y comprobantes requieren carpetas persistentes absolutas y separadas.')
RESERVATION_PROOF_ROOT = LOCAL_PRIVATE_ROOT / 'reservation-proofs'
EVENT_PROOF_ROOT = LOCAL_PRIVATE_ROOT / 'event-proofs'
LOCAL_LOG_ROOT = Path(os.environ.get('LOCAL_LOG_ROOT', str(BASE_DIR / 'var' / 'log')))
LOCAL_LOG_ROOT.mkdir(parents=True, exist_ok=True)
LOGGING = {
    'version':1, 'disable_existing_loggers':False,
    'filters':{'safe':{'()':'apps.localnode.logging.SafeEventFilter'}},
    'formatters':{'local':{'format':'{asctime} {levelname} {name} {message}', 'style':'{'}},
    'handlers':{name:{'class':'logging.handlers.RotatingFileHandler','filename':str(LOCAL_LOG_ROOT / (name+'.log')),
        'maxBytes':5*1024*1024,'backupCount':5,'encoding':'utf-8','filters':['safe'],'formatter':'local'} for name in ('application','printing')},
    'root':{'handlers':['application'],'level':'INFO'},
    'loggers':{'django.server':{'handlers':['application'],'level':'WARNING','propagate':False},
               'django':{'handlers':['application'],'level':'WARNING','propagate':False},
               'apps.printing':{'handlers':['printing'],'level':'INFO','propagate':False},
               'waitress':{'handlers':['application'],'level':'WARNING','propagate':False}}
}

if SYNC_ENABLED:
    LOGGING['filters']['sync_safe'] = {'()':'apps.sync.logging.SyncSafeFilter'}
    LOGGING['handlers']['sync'] = {'class':'logging.handlers.RotatingFileHandler','filename':str(LOCAL_LOG_ROOT/'sync.log'),
        'maxBytes':5*1024*1024,'backupCount':5,'encoding':'utf-8','filters':['sync_safe'],'formatter':'local'}
    LOGGING['loggers']['apps.sync'] = {'handlers':['sync'],'level':'INFO','propagate':False}
