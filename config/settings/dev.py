"""Desarrollo local en macOS."""
from .base import *  # noqa: F403

if DEPLOYMENT_MODE != 'development':
    raise ImproperlyConfigured('Selecciona el perfil de settings correspondiente al modo de despliegue.')

# Optional exact Wi-Fi address for a local pilot; production settings never read it.
DEV_LAN_HOST = os.environ.get('DEV_LAN_HOST', '').strip()
if DEV_LAN_HOST:
    from ipaddress import ip_address
    try:
        address = ip_address(DEV_LAN_HOST)
        if address.is_unspecified or address.is_multicast:
            raise ValueError
    except ValueError:
        raise ImproperlyConfigured('DEV_LAN_HOST requiere una IP concreta, sin esquema, puerto, ruta ni comodines.') from None
    host = f'[{address.compressed}]' if address.version == 6 else address.compressed
    if host not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(host)
    origin = f'http://{host}:8000'
    if origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(origin)
