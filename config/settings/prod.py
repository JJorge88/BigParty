"""Separación mínima para producción; el despliegue queda fuera de la Fase 0."""
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403

DEPLOYMENT_MODE = os.environ.get('DEPLOYMENT_MODE', 'cloud')
DEBUG = False
if not ALLOWED_HOSTS or "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured("Producción requiere DJANGO_ALLOWED_HOSTS explícitos.")

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
