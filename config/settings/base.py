"""Configuración compartida. Las variables del proceso prevalecen sobre .env."""
import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env")


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


SECRET_KEY = required_env("DJANGO_SECRET_KEY")
DEBUG = env_bool("DJANGO_DEBUG")
ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",")
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
    "django.contrib.sessions.middleware.SessionMiddleware",
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
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
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
