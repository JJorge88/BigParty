"""Outbox transaccional, transporte tras commit y acciones explícitas auditadas."""
from datetime import timedelta
from functools import partial
import uuid

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection, transaction
from django.utils import timezone
from apps.audit.models import AuditLog
from apps.orders.models import PreparationTicket, TableOrder
from apps.payments.queries import get_financial_summary
from .models import Printer, PrintJob
from . import rendering
from .backends import get_backend, PrinterError

LOCK_NAMESPACE = 73190422


def require(user, permission):
    if not user or not user.is_active or not user.has_perm('printing.' + permission):
        raise PermissionDenied('No tienes permiso para esta operación de impresión.')


def scope(user, area_id, scope_area):
    if user.has_perm('printing.manage_printers'):
        return
    if scope_area is None or area_id != scope_area.pk:
        raise PermissionDenied('La impresión no pertenece al área de esta estación.')


def audit(job, user, action, **data):
    AuditLog.objects.create(user=user, action='printing.' + action, entity='printing.printjob', entity_id=str(job.pk),
                            data={'printer_id':job.printer_id, 'order_id':job.order_id, 'ticket_id':job.preparation_ticket_id, **data})


def resolve_printer(destination):
    if destination == 'kitchen':
        return Printer.objects.filter(printer_type='KITCHEN', is_active=True).first()
    if destination.startswith('bar:'):
        return Printer.objects.filter(printer_type='BAR', area_id=int(destination[4:]), is_active=True).first()
    return None


def schedule(job):
    # Los callbacks no se ejecutan si se revierte el pedido/pago que originó el trabajo.
    if job.status == 'PENDING':
        transaction.on_commit(partial(print_job, job.pk), robust=True)


def create_job(*, printer, destination_key, snapshot, **fields):
    missing = printer is None
    job = PrintJob.objects.create(printer=printer, destination_key=destination_key, payload_snapshot=snapshot,
        status='FAILED' if missing else 'PENDING', last_error='No hay impresora activa para esta ruta. Configúrala y reintenta.' if missing else '', **fields)
    audit(job, job.created_by, 'created', status=job.status, reprint_of=job.reprint_of_id)
    schedule(job)
    return job


@transaction.atomic
def create_print_jobs_for_ticket(ticket):
    ticket = PreparationTicket.objects.select_for_update().select_related('order', 'created_by').get(pk=ticket.pk)
    groups = {}
    for item in ticket.items.select_related('area').order_by('pk'):
        if item.route == 'NONE':
            continue
        key = 'kitchen' if item.route == 'KITCHEN' else f'bar:{item.area_id}'
        groups.setdefault(key, []).append(item)
    jobs = []
    for key, items in groups.items():
        existing = ticket.print_jobs.filter(destination_key=key, reprint_of__isnull=True).first()
        if existing:
            jobs.append(existing)
            continue
        printer = resolve_printer(key)
        destination = printer.name if printer else 'Cocina' if key == 'kitchen' else f'Barra · {items[0].area.name}'
        jobs.append(create_job(printer=printer, destination_key=key, snapshot=rendering.ticket_snapshot(ticket, items, printer, destination),
            preparation_ticket=ticket, order=ticket.order, created_by=ticket.created_by,
            job_type={'CANCELLATION':'CANCELLATION','UPDATE':'UPDATE'}.get(ticket.ticket_type,'PREPARATION')))
    return jobs


def _try_lock(job_id):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_try_advisory_lock(%s, %s)', [LOCK_NAMESPACE, job_id])
        return cursor.fetchone()[0]


def _unlock(job_id):
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_unlock(%s, %s)', [LOCK_NAMESPACE, job_id])


def print_job(job):
    """Un intento; no reintenta FAILED ni PRINTING. El socket nunca vive en una transacción."""
    if connection.in_atomic_block:
        raise RuntimeError('La impresión debe ejecutarse después del commit.')
    job_id = job.pk if isinstance(job, PrintJob) else job
    if not _try_lock(job_id):
        return PrintJob.objects.get(pk=job_id)
    try:
        with transaction.atomic():
            current = PrintJob.objects.select_for_update(of=('self',)).select_related('printer').get(pk=job_id)
            if current.status != 'PENDING':
                return current
            current.status = 'PRINTING'
            current.claim_token = uuid.uuid4()
            current.printing_started_at = timezone.now()
            current.attempt_count += 1
            current.last_error = ''
            current.delivery_uncertain = False
            current.backend_used = settings.PRINTER_BACKEND
            current.save()
            audit(current, current.created_by, 'attempt_started', attempt=current.attempt_count)
        error, uncertain, output = '', False, ''
        try:
            if not current.printer or not current.printer.is_active:
                raise PrinterError('La impresora está inactiva o no configurada.')
            output = get_backend().send(current)
        except Exception as exc:
            error = str(exc)[:2000] or type(exc).__name__
            uncertain = getattr(exc, 'uncertain', False)
        with transaction.atomic():
            finished = PrintJob.objects.select_for_update().get(pk=job_id)
            if finished.status == 'PRINTING' and finished.claim_token == current.claim_token:
                finished.status = 'FAILED' if error else 'PRINTED'
                finished.last_error, finished.delivery_uncertain, finished.output_path = error, uncertain, output
                finished.printed_at = None if error else timezone.now()
                finished.save()
                audit(finished, finished.created_by, 'failed' if error else 'printed', attempt=finished.attempt_count, uncertain=uncertain, backend=finished.backend_used)
            return finished
    finally:
        _unlock(job_id)


@transaction.atomic
def retry_print_job(job, user, *, scope_area=None):
    require(user, 'retry_print_job')
    current = PrintJob.objects.select_for_update(of=('self',)).select_related('order', 'printer').get(pk=job.pk)
    scope(user, current.order.area_id if current.order_id else current.printer.area_id if current.printer_id else None, scope_area)
    if current.status != 'FAILED':
        raise ValidationError('Solo se puede reintentar un trabajo fallido.')
    printer = resolve_printer(current.destination_key) if current.destination_key.startswith(('bar:', 'kitchen')) else current.printer
    if not printer or not printer.is_active:
        raise ValidationError('Configura una impresora activa para esta ruta antes de reintentar.')
    current.printer, current.status = printer, 'PENDING'
    current.save(update_fields=['printer','status','updated_at'])
    audit(current, user, 'retry_requested', previous_error=current.last_error, uncertain=current.delivery_uncertain)
    schedule(current)
    return current


@transaction.atomic
def reprint_ticket(ticket, printer, user, reason, *, scope_area=None, request_key=None):
    require(user, 'reprint_preparation_ticket')
    ticket = PreparationTicket.objects.select_for_update().select_related('order').get(pk=ticket.pk)
    scope(user, ticket.order.area_id, scope_area)
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('Indica el motivo de reimpresión.')
    printer = Printer.objects.get(pk=printer.pk)
    if not printer.is_active:
        raise ValidationError('La impresora está inactiva.')
    original = ticket.print_jobs.filter(printer=printer, reprint_of__isnull=True).first()
    if original is None:
        raise ValidationError('La impresora no corresponde a esta comanda. Revisa la ruta original.')
    if original.status != 'PRINTED':
        raise ValidationError('Reintenta el trabajo fallido o recupera el trabajo en curso antes de crear una copia.')
    if request_key:
        existing = PrintJob.objects.filter(request_key=request_key, reprint_of=original).first()
        if existing:
            return existing
    return create_job(printer=printer, destination_key=original.destination_key,
        snapshot=rendering.copy_snapshot(original, reason.strip()), job_type=original.job_type,
        preparation_ticket=ticket, order=ticket.order, reprint_of=original, reason=reason.strip(), created_by=user,
        **({'request_key':request_key} if request_key else {}))


@transaction.atomic
def print_receipt(order, printer, user, *, scope_area=None, request_key=None):
    require(user, 'print_customer_receipt')
    order = TableOrder.objects.select_for_update().get(pk=order.pk)
    scope(user, order.area_id, scope_area)
    summary = get_financial_summary(order)
    if order.status != 'CLOSED' or summary['outstanding_balance'] or summary['pending_verification'] or order.lines.filter(status='DRAFT').exists():
        raise ValidationError('El recibo se solicita después de liquidar y cerrar la cuenta.')
    area_id = order.cash_session.register.area_id if order.order_type == 'QUICK_SALE' else order.area_id
    destination = f'bar:{area_id}'
    expected = resolve_printer(destination)
    if printer is not None and (expected is None or printer.pk != expected.pk):
        raise ValidationError('El recibo corresponde a la barra del área de esta cuenta.')
    printer = expected
    if request_key:
        existing = order.print_jobs.filter(request_key=request_key, job_type='RECEIPT').first()
        if existing:
            return existing
    original = order.print_jobs.filter(job_type='RECEIPT', reprint_of__isnull=True).first()
    if original and original.status != 'PRINTED':
        # Dobles clics y solicitudes mientras falla/conecta conservan un solo original.
        return original
    reason = 'Nueva solicitud de recibo por el cliente' if original else ''
    snapshot = rendering.copy_snapshot(original, reason) if original else rendering.receipt_snapshot(order, printer)
    return create_job(printer=printer, destination_key=destination, snapshot=snapshot, job_type='RECEIPT', order=order,
        created_by=user, reprint_of=original, reason=reason, **({'request_key':request_key} if request_key else {}))


@transaction.atomic
def print_test_page(printer, user):
    require(user, 'test_printer')
    require(user, 'manage_printers')
    printer = Printer.objects.get(pk=printer.pk)
    if not printer.is_active:
        raise ValidationError('Activa la impresora antes de probarla.')
    return create_job(printer=printer, destination_key=f'test:{printer.pk}', snapshot=rendering.test_snapshot(printer), job_type='TEST', created_by=user)


def get_printer_status(printer):
    last = printer.jobs.order_by('-pk').first()
    return {'active':printer.is_active, 'configured':bool(printer.host), 'backend':settings.PRINTER_BACKEND,
            'last_status':last.status if last else None, 'last_status_label':last.get_status_display() if last else '', 'last_error':last.last_error if last else '',
            'last_success':printer.jobs.filter(status='PRINTED').order_by('-printed_at').values_list('printed_at',flat=True).first()}


def order_print_status(order):
    rows = list(order.print_jobs.exclude(job_type__in=['RECEIPT','TEST']).filter(status__in=['FAILED','PRINTING','PENDING']))
    failed = list(dict.fromkeys(row.payload_snapshot.get('destination', 'Impresora') for row in rows if row.status == 'FAILED'))
    waiting = any(row.status != 'FAILED' for row in rows)
    message = 'Pedido registrado. No se pudo imprimir en ' + ', '.join(failed) + '. Avisa a Caja/Gerencia.' if failed else 'Pedido registrado. Impresión en curso.' if waiting else ''
    return {'message':message, 'failed':bool(failed), 'waiting':waiting}


def recover_stale_jobs(*, seconds=None):
    cutoff = timezone.now() - timedelta(seconds=seconds or settings.PRINTER_STALE_SECONDS)
    recovered = []
    for job_id in PrintJob.objects.filter(status='PRINTING', printing_started_at__lt=cutoff).values_list('pk',flat=True):
        with transaction.atomic():
            # Un proceso vivo mantiene este candado fuera de la transacción durante I/O.
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_try_advisory_xact_lock(%s, %s)', [LOCK_NAMESPACE,job_id])
                if not cursor.fetchone()[0]:
                    continue
            job = PrintJob.objects.select_for_update().get(pk=job_id)
            if job.status != 'PRINTING' or job.printing_started_at >= cutoff:
                continue
            job.status, job.delivery_uncertain = 'FAILED', True
            job.last_error = 'Proceso interrumpido. Verifica si salió papel antes de reintentar manualmente.'
            job.save(update_fields=['status','delivery_uncertain','last_error','updated_at'])
            audit(job, None, 'stale_recovered')
            recovered.append(job.pk)
    return recovered
