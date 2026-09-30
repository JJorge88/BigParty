"""Read-only invariants and recovery diagnostics. No automatic repairs."""
from pathlib import Path
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.models import Count, F, Q, Sum
from django.db.migrations.executor import MigrationExecutor
from apps.orders.models import TableOrder,OrderTableLink
from apps.payments.models import Payment,PaymentAllocation
from apps.payments.queries import get_financial_summary
from apps.catalog.models import Product
from apps.cash.models import CashSession
from apps.events.models import EventTicket,EventPurchasePayment,Event
from apps.reservations.models import Reservation,ReservationPayment
from apps.sync.models import SyncIdentity,SyncCursor,SyncRuntimeState


def integrity():
    errors=[]
    checks={
        'DUPLICATE_ACTIVE_TABLE':TableOrder.objects.filter(status__in=['OPEN','PARTIALLY_PAID','PAYMENT_PENDING']).exclude(primary_table=None).values('primary_table').annotate(n=Count('pk')).filter(n__gt=1).count(),
        'DUPLICATE_ACTIVE_LINK':OrderTableLink.objects.filter(released_at=None).values('table').annotate(n=Count('pk')).filter(n__gt=1).count(),
        'NEGATIVE_STOCK':Product.objects.filter(stock_quantity__lt=0).count(),
        'DUPLICATE_OPEN_CASH':CashSession.objects.filter(status='OPEN').values('register').annotate(n=Count('pk')).filter(n__gt=1).count(),
        'USED_TICKET_WITHOUT_TIME':EventTicket.objects.filter(status='USED',used_at=None).count(),
        'ARRIVED_WITHOUT_ORDER':Reservation.objects.filter(status='ARRIVED',order=None).count(),
        'DUPLICATE_SYNC_IDENTITY':SyncIdentity.objects.values('model_label','object_pk').annotate(n=Count('pk')).filter(n__gt=1).count(),
        'OVERALLOCATED_PAYMENT':Payment.objects.annotate(allocated=Sum('allocations__amount')).filter(allocated__gt=F('amount')).count(),
    }
    closed_balance=0
    for order in TableOrder.objects.filter(status='CLOSED').iterator(chunk_size=100):
        summary=get_financial_summary(order)
        if summary['outstanding_balance'] or summary['pending_verification']:closed_balance+=1
    checks['CLOSED_ORDER_WITH_BALANCE']=closed_balance
    from apps.sync.models import CloudSyncChange
    state=SyncRuntimeState.objects.filter(pk=1).first()
    from django.db.models import Max
    maximum=CloudSyncChange.objects.aggregate(n=Max('sequence'))['n'] or 0
    checks['INVALID_CLOUD_FEED']=int(settings.DEPLOYMENT_MODE=='cloud' and (state.feed_sequence if state else 0)!=maximum)
    from apps.sync.models import SyncInboxEvent
    checks['INVALID_CURSOR']=SyncCursor.objects.filter(~Q(source='cloud')|Q(last_sequence__lt=0)).count()
    if settings.DEPLOYMENT_MODE=='local_node':
        received=SyncInboxEvent.objects.filter(source='cloud').count()
        checks['INVALID_CURSOR']+=SyncCursor.objects.filter(source='cloud',last_sequence__gt=received).count()
    for code,count in checks.items():
        if count:errors.append({'code':code,'count':count})
    return {'checks':checks,'errors':errors}


def media_references():
    missing=0
    for model,field in ((Event,'image'),(Product,'image'),(ReservationPayment,'proof_image'),(EventPurchasePayment,'proof_image')):
        for row in model.objects.exclude(**{field:''}).only(field).iterator(chunk_size=100):
            file=getattr(row,field)
            try:
                if not file.storage.exists(file.name):missing+=1
            except (OSError,ValueError):missing+=1
    return missing


def restored_report():
    result=integrity()
    executor=MigrationExecutor(connection)
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):result['errors'].append({'code':'PENDING_MIGRATIONS','count':1})
    labels=['accounts.User','venues.Area','catalog.Product','orders.TableOrder','payments.Payment','cash.CashSession',
            'inventory.InventoryMovement','reservations.Reservation','events.Event','events.EventTicket',
            'sync.SyncIdentity','sync.SyncOutboxEvent','sync.SyncInboxEvent','sync.SyncCursor','localnode.LocalNodeIdentity']
    result['counts']={label:apps.get_model(label).objects.count() for label in labels}
    if settings.DEPLOYMENT_MODE=='local_node' and result['counts']['localnode.LocalNodeIdentity']!=1:
        result['errors'].append({'code':'LOCAL_NODE_IDENTITY_MISSING','count':1})
    missing=media_references()
    if missing:result['errors'].append({'code':'MISSING_MEDIA_REFERENCES','count':missing})
    result['sync_cursors']=list(SyncCursor.objects.values('source','last_sequence'))
    return result
