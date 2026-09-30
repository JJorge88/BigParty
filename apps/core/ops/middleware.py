import logging
import uuid
from django.conf import settings
from django.http import HttpResponse
from . import recovery,throttle

logger=logging.getLogger('apps.hardening')

class OperationsSecurityMiddleware:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        request.support_reference=uuid.uuid4().hex[:12]
        path=request.path_info
        active=recovery.status()['active']
        management=path.startswith('/gerencia/')
        allowed_auth=path in ('/gerencia/acceso/','/gerencia/salir/','/gerencia/actividad/')
        if active and path not in ('/healthz/','/readyz/') and not path.startswith('/static/') and not allowed_auth:
            if not (management and request.method in ('GET','HEAD')):
                return self.headers(HttpResponse('BIG PARTY · Modo recuperación. Operación suspendida.',status=503),request)
        limit=throttle.limit_for(path)
        if settings.RATE_LIMIT_ENABLED and limit and (request.method=='POST' or limit[0]=='sync'):
            try:accepted,retry=throttle.accept(limit[0],request.META.get('REMOTE_ADDR','unknown'),limit[1])
            except (OSError,ValueError,KeyError,TypeError):
                return self.headers(HttpResponse('Acceso temporalmente no disponible.',status=503),request)
            if not accepted:
                response=HttpResponse('Demasiados intentos. Espera unos minutos.',status=429)
                response['Retry-After']=str(retry)
                return self.headers(response,request)
        response=self.get_response(request)
        if response.status_code>=500:
            logger.error('server_error',extra={'support_reference':request.support_reference,'status_code':response.status_code})
        return self.headers(response,request)
    def headers(self,response,request):
        response['X-Request-ID']=request.support_reference
        if settings.SECURITY_HEADERS_ENABLED:
            # Existing templates use dynamic style attributes for maps; scripts remain strictly self-hosted.
            response['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; worker-src 'self' blob:; media-src 'self' blob:; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
            if request.path_info == '/':
                response['Content-Security-Policy'] += '; frame-src https://www.openstreetmap.org'
            response['Permissions-Policy']='camera=(self), microphone=(), geolocation=()'
            response['Referrer-Policy']='same-origin'
            response['X-Content-Type-Options']='nosniff'
        return response


def context(request):
    return {'recovery_active':recovery.status()['active']}
