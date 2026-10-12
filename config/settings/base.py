"""Configuración compartida. Las variables del proceso prevalecen sobre .env."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(os.environ.get("BIGPARTY_ENV_FILE", BASE_DIR / ".env"))


def required_env(name):
    value = os.environ.get(name, "").strip()
    if not value or value.startswith("replace-with-"):
        raise ImproperlyConfigured(f"Configura {name} en el entorno o en .env.")
    return value


def env_bool(name, default=False):
    value = os.environ.get(name, str(default)).strip().lower()
    if value not in {"true", "false", "1", "0"}:
        raise ImproperlyConfigured(f"{name} debe ser True, False, 1 o 0.")
    return value in {"true", "1"}


DEPLOYMENT_MODE = os.environ.get('DEPLOYMENT_MODE', 'development')
if DEPLOYMENT_MODE not in {'development', 'cloud', 'local_node'}:
    raise ImproperlyConfigured('DEPLOYMENT_MODE debe ser development, cloud o local_node.')
APP_VERSION = os.environ.get('APP_VERSION', '')
APP_COMMIT = os.environ.get('APP_COMMIT', '')
ACCESS_SNAPSHOT_SIGNING_KEY = os.environ.get('ACCESS_SNAPSHOT_SIGNING_KEY', '')
ACCESS_SNAPSHOT_SOURCE = os.environ.get('ACCESS_SNAPSHOT_SOURCE', 'bigparty-cloud')
CSRF_TRUSTED_ORIGINS = [v.strip() for v in os.environ.get('CSRF_TRUSTED_ORIGINS', '').split(',') if v.strip()]
SECRET_KEY = required_env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("ALLOWED_HOSTS", os.environ.get("DJANGO_ALLOWED_HOSTS", "")).split(",")
    if host.strip()
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.core.apps.CoreConfig",
    "apps.audit.apps.AuditConfig",
    "apps.venues.apps.VenuesConfig",
    "apps.tables.apps.TablesConfig",
    "apps.catalog.apps.CatalogConfig",
    "apps.inventory.apps.InventoryConfig",
    "apps.orders.apps.OrdersConfig",
    "apps.printing.apps.PrintingConfig",
    "apps.payments.apps.PaymentsConfig",
    "apps.cash.apps.CashConfig",
    "apps.operations.apps.OperationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.localnode.middleware.LocalNodeBoundaryMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "apps.operations.management.middleware.ManagementSessionMiddleware",
    "apps.events.middleware.GuardSessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": required_env("DB_NAME"),
        "USER": required_env("DB_USER"),
        "PASSWORD": required_env("DB_PASSWORD"),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
    },
}

# Definido desde la primera migración; conserva grupos y permisos de AbstractUser.
AUTH_USER_MODEL = "accounts.User"
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "es"
TIME_ZONE = os.environ.get("TIME_ZONE", "America/Guatemala")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/archivos-publicos/"
MEDIA_ROOT = BASE_DIR / "media"
# MEDIA_ROOT contiene únicamente imágenes públicas. Django aplica estos permisos
# después de guardar aunque el servicio use una umask restrictiva para datos privados.
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Acceso de tablets: valores centrales compartidos por backend e interfaz.
OPERATIONAL_IDLE_TIMEOUT_SECONDS = 120
OPERATIONAL_PIN_MAX_ATTEMPTS = 5
OPERATIONAL_PIN_LOCK_SECONDS = 300
OPERATIONAL_DEVICE_COOKIE_AGE = 60 * 60 * 24 * 365

# Caja Windows: acceso independiente de la tablet y sin mantener sesiones abandonadas.
CASH_IDLE_TIMEOUT_SECONDS = 600
CASH_PIN_MAX_ATTEMPTS = 5
CASH_PIN_LOCK_SECONDS = 300
CASH_REGISTER_COOKIE_AGE = 365 * 24 * 60 * 60

# El nodo local ejecuta la impresión. El entorno elige el backend, independientemente de DEBUG.
PRINTER_BACKEND = os.environ.get("PRINTER_BACKEND", "debug")
if PRINTER_BACKEND not in {"debug", "network"}:
    raise ImproperlyConfigured("PRINTER_BACKEND debe ser debug o network.")
PRINTER_DEBUG_DIR = Path(os.environ.get("PRINTER_DEBUG_DIR", str(BASE_DIR / "var" / "print-jobs")))
PRINTER_CONNECT_TIMEOUT = float(os.environ.get("PRINTER_CONNECT_TIMEOUT", "1"))
PRINTER_WRITE_TIMEOUT = float(os.environ.get("PRINTER_WRITE_TIMEOUT", "2"))
PRINTER_STALE_SECONDS = int(os.environ.get("PRINTER_STALE_SECONDS", "120"))
if not (0 < PRINTER_CONNECT_TIMEOUT <= 5 and 0 < PRINTER_WRITE_TIMEOUT <= 5 and PRINTER_STALE_SECONDS >= 30):
    raise ImproperlyConfigured("Timeouts de impresora: mayor que 0 y máximo 5 segundos; stale mínimo 30.")

# Gerencia usa una sesión Django separada y 30 minutos de inactividad.
MANAGEMENT_IDLE_TIMEOUT_SECONDS = 30 * 60
MANAGEMENT_SESSION_COOKIE_NAME = "bigparty_management"

# Comprobantes privados: nunca dentro de MEDIA_ROOT ni servidos por static().
RESERVATION_PROOF_ROOT = BASE_DIR / 'private' / 'reservation-proofs'
PUBLIC_BASE_URL = os.environ.get('PUBLIC_BASE_URL', 'http://localhost:8000').rstrip('/')
INSTALLED_APPS += ['apps.reservations']

INSTALLED_APPS += ['apps.events']
EVENT_PROOF_ROOT = BASE_DIR / 'private' / 'event-proofs'
EVENT_GUARD_IDLE_SECONDS = 30 * 60

# Imágenes editoriales públicas: rutas relativas a static, reemplazables sin CMS.
PUBLIC_HERO_IMAGE = os.environ.get('PUBLIC_HERO_IMAGE', 'images/public/nightlife-hero.webp')
PUBLIC_LEVEL_IMAGES = {
    'sport_bar': os.environ.get('PUBLIC_SPORT_BAR_IMAGE', 'images/public/sport-bar-concept.webp'),
    'discoteca': os.environ.get('PUBLIC_DISCOTECA_IMAGE', 'images/public/discoteca-concept.webp'),
    'premium': os.environ.get('PUBLIC_PREMIUM_IMAGE', 'images/public/premium-concept.webp'),
}
PUBLIC_RESERVATION_IMAGE = os.environ.get('PUBLIC_RESERVATION_IMAGE', 'images/public/reservation-concept.webp')
PUBLIC_EVENT_FALLBACK_IMAGE = os.environ.get('PUBLIC_EVENT_FALLBACK_IMAGE', 'images/public/event-fallback-concept.webp')

# Invitación temporal; independiente de reservas, ventas y entradas.
PUBLIC_INVITATION_ENABLED = env_bool('PUBLIC_INVITATION_ENABLED', True)
PUBLIC_INVITATION_STARTS_AT = os.environ.get('PUBLIC_INVITATION_STARTS_AT', '2026-10-22T14:00:00-06:00')

INSTALLED_APPS += ['apps.localnode.apps.LocalnodeConfig']

# Explicit application sync. Disabled installations retain 4B behavior.
INSTALLED_APPS += ['apps.sync.apps.SyncConfig']
SYNC_ENABLED = env_bool('SYNC_ENABLED', False)
SYNC_CLOUD_URL = os.environ.get('SYNC_CLOUD_URL', '').rstrip('/')
SYNC_SHARED_SECRET = os.environ.get('SYNC_SHARED_SECRET', '')
SYNC_NODE_UUID = os.environ.get('SYNC_NODE_UUID', '')
SYNC_PROTOCOL_VERSION = int(os.environ.get('SYNC_PROTOCOL_VERSION', '1'))
SYNC_BATCH_SIZE = int(os.environ.get('SYNC_BATCH_SIZE', '100'))
SYNC_INTERVAL_SECONDS = int(os.environ.get('SYNC_INTERVAL_SECONDS', '15'))
SYNC_MAX_BACKOFF_SECONDS = int(os.environ.get('SYNC_MAX_BACKOFF_SECONDS', '300'))
SYNC_CONNECT_TIMEOUT = float(os.environ.get('SYNC_CONNECT_TIMEOUT', '3'))
SYNC_READ_TIMEOUT = float(os.environ.get('SYNC_READ_TIMEOUT', '8'))
SYNC_MAX_BODY_BYTES = int(os.environ.get('SYNC_MAX_BODY_BYTES', str(20 * 1024 * 1024)))
SYNC_ALLOW_HTTP_DEVELOPMENT = env_bool('SYNC_ALLOW_HTTP_DEVELOPMENT', False)
SYNC_COMPATIBLE_APP_VERSIONS = [v for v in (os.environ.get('SYNC_COMPATIBLE_APP_VERSIONS') or APP_VERSION).split(',') if v]
if not (1 <= SYNC_BATCH_SIZE <= 1000 and 1 <= SYNC_INTERVAL_SECONDS <= SYNC_MAX_BACKOFF_SECONDS <= 3600
        and 0 < SYNC_CONNECT_TIMEOUT <= 10 and 0 < SYNC_READ_TIMEOUT <= 30
        and 1024 <= SYNC_MAX_BODY_BYTES <= 20 * 1024 * 1024 and SYNC_PROTOCOL_VERSION == 1):
    raise ImproperlyConfigured('Configuración de límites/protocolo sync inválida.')

MIDDLEWARE.insert(2, 'apps.sync.middleware.SyncAuthorityMiddleware')
TEMPLATES[0]['OPTIONS']['context_processors'].append('apps.sync.context_processors.sync_authority')

# 4D operations. Persistent directories must be outside public roots/the checkout.
BACKUP_ROOT = os.environ.get('BACKUP_ROOT', '')
BACKUP_SECONDARY_ROOT = os.environ.get('BACKUP_SECONDARY_ROOT', '')
BACKUP_OFFSITE_COMMAND = os.environ.get('BACKUP_OFFSITE_COMMAND', '')  # JSON argv; never a shell expression
BACKUP_KEEP_HOURLY = int(os.environ.get('BACKUP_KEEP_HOURLY', '4'))
BACKUP_KEEP_DAILY = int(os.environ.get('BACKUP_KEEP_DAILY', '14'))
BACKUP_KEEP_WEEKLY = int(os.environ.get('BACKUP_KEEP_WEEKLY', '8'))
BACKUP_KEEP_MONTHLY = int(os.environ.get('BACKUP_KEEP_MONTHLY', '6'))
BACKUP_TIMEOUT_SECONDS = int(os.environ.get('BACKUP_TIMEOUT_SECONDS', '1800'))
BACKUP_MAX_AGE_HOURS = int(os.environ.get('BACKUP_MAX_AGE_HOURS', '8'))
MIN_FREE_DISK_GB = float(os.environ.get('MIN_FREE_DISK_GB', '2'))
PG_BIN_DIR = os.environ.get('PG_BIN_DIR', '')
RECOVERY_MODE = env_bool('RECOVERY_MODE', False)
OPERATIONS_STATE_ROOT = Path(os.environ.get('OPERATIONS_STATE_ROOT', str(BASE_DIR / 'var' / 'operations')))
RATE_LIMIT_ENABLED = env_bool('RATE_LIMIT_ENABLED', DEPLOYMENT_MODE != 'development')
RATE_LIMIT_WINDOW_SECONDS = int(os.environ.get('RATE_LIMIT_WINDOW_SECONDS', '300'))
RATE_LIMIT_LOGIN = int(os.environ.get('RATE_LIMIT_LOGIN', '20'))
RATE_LIMIT_PUBLIC = int(os.environ.get('RATE_LIMIT_PUBLIC', '12'))
RATE_LIMIT_UPLOAD = int(os.environ.get('RATE_LIMIT_UPLOAD', '10'))
RATE_LIMIT_SYNC = int(os.environ.get('RATE_LIMIT_SYNC', '120'))
SYNC_SHARED_SECRET_PREVIOUS = os.environ.get('SYNC_SHARED_SECRET_PREVIOUS', '')
SYNC_SECRET_PREVIOUS_UNTIL = os.environ.get('SYNC_SECRET_PREVIOUS_UNTIL', '')
SECURITY_HEADERS_ENABLED = env_bool('SECURITY_HEADERS_ENABLED', DEPLOYMENT_MODE != 'development')
if min(BACKUP_KEEP_HOURLY, BACKUP_KEEP_DAILY, BACKUP_KEEP_WEEKLY, BACKUP_KEEP_MONTHLY) < 0 or max(BACKUP_KEEP_HOURLY, BACKUP_KEEP_DAILY, BACKUP_KEEP_WEEKLY, BACKUP_KEEP_MONTHLY) == 0:
    raise ImproperlyConfigured('Configura una retención de backups positiva.')
if MIN_FREE_DISK_GB < 0 or not 30 <= BACKUP_TIMEOUT_SECONDS <= 86400 or min(RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_LOGIN, RATE_LIMIT_PUBLIC, RATE_LIMIT_UPLOAD, RATE_LIMIT_SYNC) < 1:
    raise ImproperlyConfigured('Límites operativos inválidos.')

MIDDLEWARE.insert(1, 'apps.core.ops.middleware.OperationsSecurityMiddleware')
TEMPLATES[0]['OPTIONS']['context_processors'].append('apps.core.ops.middleware.context')

BACKUP_SCHEDULE_DESCRIPTION = os.environ.get('BACKUP_SCHEDULE_DESCRIPTION', '')
