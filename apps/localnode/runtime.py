"""python -m apps.localnode.runtime: bounded DB startup, then Waitress. No cloud calls."""
import logging
import os
import sys
import time


def wait_for_database(connection, timeout=60, *, clock=time.monotonic, sleep=time.sleep):
    from django.db import DatabaseError
    deadline = clock() + timeout
    while True:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            return True
        except DatabaseError:
            connection.close()
            remaining = deadline - clock()
            if remaining <= 0: return False
            sleep(min(2, remaining))


def main():
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local_node')
    try:
        import django
        django.setup()
        from django.conf import settings
        from django.db import connection
        from django.core.wsgi import get_wsgi_application
        from waitress import serve
        if settings.DEPLOYMENT_MODE != 'local_node':
            raise RuntimeError('Perfil incorrecto')
        logger = logging.getLogger('apps.localnode')
        logger.info('node_starting')
        if not wait_for_database(connection, settings.LOCAL_NODE_DB_WAIT_SECONDS):
            logger.error('database_unavailable')
            print('PostgreSQL no está disponible tras la espera limitada. Revisa el servicio local.', file=sys.stderr)
            return 1
        from .diagnostics import inspect_node
        checks, _ = inspect_node()
        if not all(ok for _, ok in checks):
            print('Ejecuta check_local_node y corrige las comprobaciones antes del arranque.', file=sys.stderr)
            return 1
        application = get_wsgi_application()
        logger.info('node_ready')
        serve(application, host=settings.LOCAL_NODE_BIND_HOST, port=settings.LOCAL_NODE_PORT, threads=8,
              trusted_proxy=settings.LOCAL_NODE_BIND_HOST, trusted_proxy_headers={'x-forwarded-proto','x-forwarded-for'},
              clear_untrusted_proxy_headers=True, expose_tracebacks=False)
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception:
        logging.getLogger('apps.localnode').error('runtime_stopped')
        print('No se pudo iniciar el nodo. Revisa configuración, migraciones, static y permisos de carpetas.', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
