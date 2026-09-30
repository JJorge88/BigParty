"""Desarrollo local en macOS."""
from .base import *  # noqa: F403

if DEPLOYMENT_MODE != 'development':
    raise ImproperlyConfigured('Selecciona el perfil de settings correspondiente al modo de despliegue.')
