from django.conf import settings
from django.core.management import call_command
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from apps.operations.management import security
from apps.operations.management.views import page
from .models import SyncRuntimeState,SyncOutboxEvent,SyncInboxEvent,SyncConflict,CloudToLocalCommand,LocalCommandInbox


@security.required
@require_http_methods(['GET','POST'])
def status(request):
    security.require(request.user,'core.view_configuration')
    if settings.DEPLOYMENT_MODE not in ('local_node','cloud'):raise Http404
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='sync' and settings.DEPLOYMENT_MODE=='local_node':
            state,_=SyncRuntimeState.objects.get_or_create(pk=1);state.sync_requested=True;state.save(update_fields=['sync_requested'])
        elif action=='retry':call_command('retry_failed_sync')
        elif action=='review':
            row=SyncConflict.objects.filter(conflict_uuid=request.POST.get('conflict'),status='OPEN').first()
            if row:
                row.status='RESOLVED';row.resolved_at=timezone.now();row.resolved_by=request.user;row.resolution='Revisado por Gerencia; sin sobrescritura automática.';row.save()
        return redirect('sync-status')
    state=SyncRuntimeState.objects.filter(pk=1).first()
    return page(request,'sync',{'runtime':state,'enabled':settings.SYNC_ENABLED,'is_local':settings.DEPLOYMENT_MODE=='local_node',
        'configured':bool(settings.SYNC_SHARED_SECRET and (settings.SYNC_CLOUD_URL if settings.DEPLOYMENT_MODE=='local_node' else settings.SYNC_NODE_UUID)),
        'pending':SyncOutboxEvent.objects.filter(status='PENDING').count(),'failed':SyncOutboxEvent.objects.filter(status='FAILED').count()+SyncInboxEvent.objects.filter(status='FAILED').count(),
        'deferred':SyncInboxEvent.objects.filter(status='DEFERRED').count(),'conflicts':SyncConflict.objects.order_by('-created_at')[:100],
        'commands':CloudToLocalCommand.objects.order_by('-created_at')[:30] if settings.DEPLOYMENT_MODE=='cloud' else LocalCommandInbox.objects.order_by('-received_at')[:30]},section='configuracion')
