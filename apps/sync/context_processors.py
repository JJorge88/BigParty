import re
from django.conf import settings

def sync_authority(request):
    path=request.path_info;cloud=settings.DEPLOYMENT_MODE=='cloud';local=settings.DEPLOYMENT_MODE=='local_node'
    readonly=settings.SYNC_ENABLED and ((cloud and path.startswith(('/gerencia/inventario/','/gerencia/catalogo/','/gerencia/usuarios/','/gerencia/jornada/'))) or (local and path.startswith(('/gerencia/eventos/','/gerencia/reservas/'))))
    if settings.SYNC_ENABLED and path.startswith('/gerencia/configuracion/') and '/sincronizacion/' not in path:
        cloud_settings=any(part in path for part in ('/reservas/','/eventos/','/bank/'))
        readonly=(local and cloud_settings) or (cloud and not cloud_settings and path!='/gerencia/configuracion/')
    if re.fullmatch(r'/gerencia/jornada/[0-9]+/pago/[0-9]+/',path):readonly=False
    return {'sync_enabled':settings.SYNC_ENABLED,'sync_cloud':cloud,'sync_local':local,'sync_readonly':readonly}
