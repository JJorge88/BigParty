"""Sesión Django aislada por cookie y ruta, sin iniciar sesión en Admin/Caja/Tablet."""
from importlib import import_module
from django.conf import settings
from django.contrib.sessions.exceptions import SessionInterrupted
from django.contrib.sessions.backends.base import UpdateError
from django.utils.cache import patch_vary_headers
from django.utils.http import http_date
import time


class ManagementSessionMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.store = import_module(settings.SESSION_ENGINE).SessionStore

    def __call__(self, request):
        if not request.path_info.startswith('/gerencia/'):
            return self.get_response(request)
        original = request.session
        request.session = self.store(request.COOKIES.get(settings.MANAGEMENT_SESSION_COOKIE_NAME))
        try:
            response = self.get_response(request)
            session = request.session
            patch_vary_headers(response, ('Cookie',))
            if session.is_empty():
                if settings.MANAGEMENT_SESSION_COOKIE_NAME in request.COOKIES:
                    response.delete_cookie(settings.MANAGEMENT_SESSION_COOKIE_NAME, path='/gerencia/', samesite='Lax')
            elif session.modified and response.status_code < 500:
                try:
                    session.save()
                except UpdateError:
                    raise SessionInterrupted('La sesión de Gerencia terminó durante la solicitud.')
                age = session.get_expiry_age()
                response.set_cookie(settings.MANAGEMENT_SESSION_COOKIE_NAME, session.session_key,
                    max_age=age, expires=http_date(time.time() + age), path='/gerencia/',
                    secure=settings.SESSION_COOKIE_SECURE, httponly=True, samesite='Lax')
            return response
        finally:
            # SessionMiddleware exterior debe seguir administrando su cookie original.
            request.session = original
