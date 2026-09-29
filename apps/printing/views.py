import uuid
from functools import wraps
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.orders.models import TableOrder
from apps.operations.cash_views import required, safe_context
from apps.operations.cash_ordering import operating
from apps.operations.views import operational_required
from .models import Printer, PrintJob
from .forms import PrinterForm
from . import services


def token(user, kind, target):
    return signing.dumps({'user':user.pk,'kind':kind,'target':target,'key':str(uuid.uuid4())},salt='printing.request.v1')


def verify_token(value, user, kind, target):
    try:
        data = signing.loads(value,salt='printing.request.v1',max_age=900)
        if (data['user'],data['kind'],data['target']) != (user.pk,kind,target):
            raise ValueError
        return uuid.UUID(data['key'])
    except (signing.BadSignature,KeyError,TypeError,ValueError):
        raise ValidationError('La solicitud venció. Actualiza la pantalla antes de continuar.')


def technical(view):
    @wraps(view)
    @login_required(login_url='admin:login')
    @never_cache
    def wrapped(request,*args,**kwargs):
        if not request.user.is_staff:
            raise PermissionDenied
        services.require(request.user,'manage_printers')
        return view(request,*args,**kwargs)
    return wrapped


@require_GET
@technical
def printers(request):
    rows = [{'printer':p,'state':services.get_printer_status(p)} for p in Printer.objects.all()]
    return render(request,'printing/printers.html',{'rows':rows,'can_test':request.user.has_perm('printing.test_printer')})


@require_http_methods(['GET','POST'])
@technical
def configure(request, pk):
    printer = get_object_or_404(Printer,pk=pk)
    form = PrinterForm(request.POST or None,instance=printer)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            from apps.audit.models import AuditLog
            AuditLog.objects.create(user=request.user,action='printing.printer_configured',entity='printing.printer',entity_id=str(printer.pk),data={'changed_fields':form.changed_data})
        messages.success(request,'Configuración guardada.')
        return redirect('printing:printers')
    return render(request,'printing/configure.html',{'form':form,'printer':printer})


@require_POST
@technical
def test(request, pk):
    try:
        job = services.print_test_page(get_object_or_404(Printer,pk=pk),request.user)
        messages.success(request,f'Prueba #{job.pk} registrada. Revisa su resultado.')
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect(reverse('printing:jobs') + '?status=all')


def job_rows(query, user):
    return [{'job':job, 'copy_token':token(user,'copy',job.pk)} for job in query.select_related('printer','order','preparation_ticket').order_by('-pk')[:100]]


def history_data(request, user, area=None):
    query = PrintJob.objects.all()
    if area is not None and not user.has_perm('printing.manage_printers'):
        query = query.filter(order__area=area)
    status = request.GET.get('status','FAILED')
    if status in PrintJob.Status.values:
        query = query.filter(status=status)
    return {'rows':job_rows(query,user),'status':status, 'can_retry':user.has_perm('printing.retry_print_job'),
            'can_reprint':user.has_perm('printing.reprint_preparation_ticket')}


@require_GET
@technical
def jobs(request):
    return render(request,'printing/jobs.html',history_data(request,request.user))


def change_job(request, user, job, action, area=None):
    if action == 'retry':
        services.retry_print_job(job,user,scope_area=area)
    elif action == 'reprint':
        key = verify_token(request.POST.get('token'),user,'copy',job.pk)
        if not job.preparation_ticket_id or not job.printer_id:
            raise ValidationError('Esta acción solo corresponde a una comanda con impresora.')
        services.reprint_ticket(job.preparation_ticket,job.printer,user,request.POST.get('reason',''),scope_area=area,request_key=key)
    else:
        raise ValidationError('Acción de impresión no disponible.')


@require_POST
@technical
def job_action(request, pk, action):
    try:
        change_job(request,request.user,get_object_or_404(PrintJob,pk=pk),action)
        messages.success(request,'Solicitud registrada. Comprueba el estado del trabajo.')
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect(reverse('printing:jobs') + '?status=all')


def cash_history_access(context):
    user = context['user']
    permission = next((p for p in ['view_printjob','retry_print_job','reprint_preparation_ticket','manage_printers'] if user.has_perm('printing.'+p)), None)
    if not permission:
        raise PermissionDenied
    operating(context,'printing.'+permission)


@require_GET
@required
def cash_jobs(request):
    try:
        cash_history_access(request.cash)
    except ValidationError as exc:
        from apps.operations.cash_views import error
        return error(request, " ".join(exc.messages), 409)
    return render(request,'printing/cash_jobs.html',{**safe_context(request.cash),**history_data(request,request.cash['user'],request.cash['register'].area)})


@require_POST
@required
def cash_job_action(request, pk, action):
    try:
        cash_history_access(request.cash)
        change_job(request,request.cash['user'],get_object_or_404(PrintJob,pk=pk),action,request.cash['register'].area)
        messages.success(request,'Solicitud registrada. Comprueba el estado del trabajo.')
    except ValidationError as exc:
        messages.error(request,' '.join(exc.messages))
    return redirect(reverse('cash_operations:print-jobs') + '?status=all')


def receipt_page(request, order, user, area, base, action_url):
    services.require(user,'print_customer_receipt')
    services.scope(user,order.area_id,area)
    if order.status != 'CLOSED':
        raise ValidationError('Cierra la cuenta pagada antes de solicitar recibo.')
    if request.method == 'POST':
        key = verify_token(request.POST.get('token'),user,'receipt',order.pk)
        services.print_receipt(order,None,user,scope_area=area,request_key=key)
        return redirect(action_url)
    return render(request,'printing/receipt.html',{'base_template':base,'order':order,'token':token(user,'receipt',order.pk),
        'receipt_job':order.print_jobs.filter(job_type='RECEIPT').order_by('-pk').first(),
        **(safe_context(request.cash) if hasattr(request,'cash') else {**request.operational, 'operator_name':user.get_full_name().strip() or user.username, 'idle_timeout':settings.OPERATIONAL_IDLE_TIMEOUT_SECONDS})})


@require_http_methods(['GET','POST'])
@required
def cash_receipt(request, order_id):
    try:
        operating(request.cash,'printing.print_customer_receipt')
        order = get_object_or_404(TableOrder,pk=order_id,area=request.cash['register'].area)
        return receipt_page(request,order,request.cash['user'],request.cash['register'].area,'operations/cash/base.html',request.path)
    except ValidationError as exc:
        from apps.operations.cash_views import error
        return error(request,' '.join(exc.messages),409)


@require_http_methods(['GET','POST'])
@operational_required
def waiter_receipt(request, order_id):
    context = request.operational
    order = get_object_or_404(TableOrder,pk=order_id,area=context['area'],order_type='TABLE')
    try:
        return receipt_page(request,order,context['user'],context['area'],'printing/waiter_base.html',request.path)
    except ValidationError as exc:
        return render(request,'operations/order_unavailable.html',{'message':' '.join(exc.messages)},status=409)
