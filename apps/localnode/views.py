from django.conf import settings
from django.db.models import Count, Q
from django.http import JsonResponse, Http404
from django.shortcuts import render
from django.views.decorators.http import require_GET
from django.views.decorators.cache import never_cache
from apps.operations.management import security
from apps.operations.management.queries import base
from apps.printing.models import Printer
from .diagnostics import database_ready
from .models import LocalNodeIdentity, LocalEventAccessSnapshot


@require_GET
@never_cache
def health(request):
    return JsonResponse({'status':'ok'})


@require_GET
@never_cache
def ready(request):
    ready = database_ready()
    return JsonResponse({'status':'ok' if ready else 'unavailable', 'database':'ok' if ready else 'unavailable'}, status=200 if ready else 503)


@require_GET
@security.required
def status(request):
    if settings.DEPLOYMENT_MODE != 'local_node':
        raise Http404
    security.require(request.user, 'core.view_configuration')
    node = LocalNodeIdentity.objects.filter(pk=1).first()
    snapshots = LocalEventAccessSnapshot.objects.filter(is_active=True).annotate(
        loaded=Count('tickets'), locally_used=Count('tickets',filter=Q(tickets__used_at__isnull=False))).order_by('-imported_at')
    return render(request, 'localnode/status.html', {
        **base(request, section='configuracion'), 'node':node,
        'database_available':database_ready(), 'backend':settings.PRINTER_BACKEND,
        'printers':Printer.objects.count(), 'active_printers':Printer.objects.filter(is_active=True).count(),
        'snapshots':snapshots, 'app_version':settings.APP_VERSION, 'app_commit':settings.APP_COMMIT[:12]})
