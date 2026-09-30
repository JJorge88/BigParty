"""Separación mínima para producción; el despliegue queda fuera de la Fase 0."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEPLOYMENT_MODE = os.environ.get('DEPLOYMENT_MODE', 'cloud')
DEBUG = False
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
