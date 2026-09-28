from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import Http404


class StaffDebugPermissionMixin(LoginRequiredMixin, PermissionRequiredMixin):
    """Acceso común a herramientas internas de comprobación."""
    login_url = "admin:login"

    def dispatch(self, request, *args, **kwargs):
        if not settings.DEBUG:
            raise Http404
        if request.user.is_authenticated and (not request.user.is_active or not request.user.is_staff):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
