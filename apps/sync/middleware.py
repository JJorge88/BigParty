import re
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from .services import enabled,source_gate


class SyncAuthorityMiddleware:
    """Reject accidental browser writes on the wrong authority before view execution."""
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if not enabled() or request.path_info.startswith('/api/sync/'):
            return self.get_response(request)
        path=request.path_info
        cloud=settings.DEPLOYMENT_MODE=='cloud'
        local_prefixes=('/operacion/','/caja/','/impresoras/','/dispositivo/','/gerencia/inventario/','/gerencia/mesas/','/gerencia/catalogo/','/gerencia/usuarios/','/gerencia/jornada/')
        cloud_prefixes=('/gerencia/eventos/','/gerencia/reservas/')
        safe_actions=('/acceso/','/salir/','/actividad/')
        forbidden=False
        if request.method not in ('GET','HEAD','OPTIONS'):
            forbidden=(cloud and path.startswith(local_prefixes)) or (not cloud and path.startswith(cloud_prefixes) and not (path.startswith('/gerencia/reservas/') and request.POST.get('action')=='arrive'))
            if cloud and re.fullmatch(r'/gerencia/jornada/[0-9]+/pago/[0-9]+/',path):forbidden=False
            if cloud and path.startswith('/gerencia/impresiones/'):forbidden=True
            if path.startswith('/gerencia/configuracion/') and '/sincronizacion/' not in path:
                cloud_settings=('/reservas/','/eventos/','/bank/')
                forbidden=cloud if not any(s in path for s in cloud_settings) else not cloud
            if path.startswith('/admin/') and not path.endswith(('/login/','/logout/')):
                pieces=path.strip('/').split('/')
                if len(pieces)>=3:
                    app=pieces[1]
                    forbidden=(cloud and app in ('accounts','venues','tables','catalog','inventory','orders','payments','cash','printing','operations')) or (not cloud and app in ('events','reservations','core'))
            if forbidden:return HttpResponse('Administrado desde BIG PARTY '+('Local Node' if cloud else 'Cloud')+'.',status=403,content_type='text/plain; charset=utf-8')
            with transaction.atomic():
                source_gate()
                return self.get_response(request)
        return self.get_response(request)
