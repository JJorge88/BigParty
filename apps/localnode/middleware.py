from django.conf import settings
from django.http import HttpResponse


class LocalNodeBoundaryMiddleware:
    """Fail closed for commercial endpoints, even if callers POST a known private URL."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.DEPLOYMENT_MODE == 'local_node':
            path = request.path_info
            if path == '/' or path in ('/sitemap.xml','/robots.txt') or path.split('/')[1] in ('eventos','reservas','entrada','dev'):
                response = HttpResponse('Sitio comercial no disponible en este nodo. Utiliza los accesos internos de BIG PARTY.', status=404, content_type='text/plain; charset=utf-8')
                response['Cache-Control'] = 'no-store'
                response['X-Robots-Tag'] = 'noindex, nofollow'
                return response
        return self.get_response(request)
