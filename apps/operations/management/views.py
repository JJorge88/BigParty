from datetime import date
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from apps.audit.models import AuditLog
from apps.cash.models import BusinessDay, CashSession
from apps.payments.models import Payment
from . import queries, security, services


def page(request, template, context=None, *, section='inicio', status=200):
    return render(request,'operations/management/'+template+'.html',{
        **queries.base(request,section), **(context or {})},status=status)


@never_cache
@sensitive_post_parameters('password')
@require_http_methods(['GET','POST'])
def login(request):
    if request.method == 'GET' and request.user.is_authenticated and security.touch(request):
        return redirect('management:home')
    form = security.ManagementAuthenticationForm(request,data=request.POST if request.method=='POST' else None)
    form.fields['username'].widget.attrs.update(autocomplete='username',placeholder='Tu usuario')
    form.fields['password'].widget.attrs.update(autocomplete='current-password',placeholder='Tu contraseña')
    if request.method=='POST' and form.is_valid():
        auth_login(request,form.get_user())
        security.start(request)
        AuditLog.objects.create(user=request.user,action='management.login',entity='accounts.user',entity_id=str(request.user.pk))
        return redirect('management:home')
    return render(request,'operations/management/login.html',{'form':form},status=400 if request.method=='POST' else 200)


@never_cache
@require_POST
def logout(request):
    if request.user.is_authenticated:
        AuditLog.objects.create(user=request.user,action='management.logout',entity='accounts.user',entity_id=str(request.user.pk))
    auth_logout(request)
    return redirect('management:login')


@require_POST
@security.required
def activity(request):
    return JsonResponse({'active':True})


@require_GET
@security.required
def home(request):
    from .workflows import actions, pending_tasks
    day = queries.current_day()
    data = queries.dashboard(day,request.user) if day else {'day':None}
    if request.user.has_perm('inventory.view_inventory'):
        from apps.catalog.models import Product
        from django.db.models import F
        data['inventory_attention'] = Product.objects.filter(is_active=True, track_inventory=True,
            stock_quantity__lte=F('minimum_stock')).count()
    data['add_actions'] = actions(request.user)
    data['daily_tasks'] = pending_tasks(request.user, data)
    return page(request,'home',data)


@require_GET
@security.required
def closures(request):
    if request.GET.get('jornada'):
        try:
            pk = int(request.GET['jornada'])
        except (ValueError,TypeError):
            raise Http404('Selecciona una jornada válida.')
        day = get_object_or_404(BusinessDay,pk=pk)
    else:
        day = queries.current_day() or BusinessDay.objects.first()
    data = queries.day_data(day,request.user) if day else {'day':None,'registers':queries.register_cards(None,[])}
    data['days'] = BusinessDay.objects.all()[:30]
    data['current_day'] = queries.current_day()
    return page(request,'closures',data,section='cierres')


@require_GET
@security.required
def cash_detail(request, day_id, session_id):
    day = get_object_or_404(BusinessDay,pk=day_id)
    session = get_object_or_404(CashSession.objects.select_related('cashier','register__area','closed_by'),pk=session_id,business_day=day)
    return page(request,'cash_detail',queries.cash_detail(day,session,request.user),section='cierres')


@require_http_methods(['GET','POST'])
@security.required
def open_day(request):
    security.require(request.user,'cash.open_business_day')
    error = ''
    if request.method=='POST':
        try:
            business_date = date.fromisoformat(request.POST.get('business_date',''))
            day = services.day_action(request,'open',business_date=business_date)
            return redirect('management:home')
        except (ValidationError,ValueError) as exc:
            error = ' '.join(exc.messages) if isinstance(exc,ValidationError) else 'Selecciona una fecha comercial válida.'
    return page(request,'open_day',{'error':error,'today':timezone.localdate(),'current_day':queries.current_day(),
        'confirmation':security.confirmation(request,'open',0,'new-day')},section='cierres',status=409 if error else 200)


@require_http_methods(['GET','POST'])
@security.required
def close_day(request, day_id):
    security.require(request.user,'cash.close_business_day')
    day = get_object_or_404(BusinessDay,pk=day_id,status='OPEN')
    error = ''
    if request.method=='POST':
        try:
            services.day_action(request,'close',day.pk)
            return redirect('management:day-result',day_id=day.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
    day.refresh_from_db()
    if day.status != 'OPEN':
        return redirect('management:day-result', day_id=day.pk)
    data = queries.day_data(day,request.user)
    if error and data['blockers']:
        error = 'La jornada tiene pendientes. Revisa los motivos antes de confirmar el cierre.'
    data.update(error=error,confirmation=security.confirmation(request,'close',day.pk,day.updated_at.isoformat()))
    return page(request,'close_day',data,section='cierres',status=409 if error else 200)


@require_GET
@security.required
def day_result(request, day_id):
    day = get_object_or_404(BusinessDay.objects.select_related('closed_by','reopened_by'),pk=day_id)
    return page(request,'day_result',queries.day_data(day,request.user),section='cierres')


@require_http_methods(['GET','POST'])
@security.required
def reopen_day(request, day_id):
    security.require(request.user,'cash.reopen_business_day')
    day = get_object_or_404(BusinessDay,pk=day_id,status='CLOSED')
    error = ''
    if request.method=='POST':
        try:
            services.day_action(request,'reopen',day.pk)
            return redirect('management:day-result',day_id=day.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
    day.refresh_from_db()
    if day.status != 'CLOSED':
        return redirect('management:day-result', day_id=day.pk)
    return page(request,'reopen_day',{'day':day,'error':error,
        'confirmation':security.confirmation(request,'reopen',day.pk,day.updated_at.isoformat())},section='cierres',status=409 if error else 200)


@require_GET
@security.required
def pending_payments(request):
    if not security.can_review(request.user):
        raise PermissionDenied
    day = queries.current_day()
    payments = Payment.objects.filter(order__business_day=day,status='PENDING',method__in=['TRANSFER','DEPOSIT']).select_related(
        'order__primary_table','order__area','recorded_by') if day else []
    return page(request,'pending_payments',{'day':day,'payments':payments})


@require_http_methods(['GET','POST'])
@security.required
def payment(request, day_id, payment_id):
    if not security.can_review(request.user):
        raise PermissionDenied
    day = get_object_or_404(BusinessDay,pk=day_id)
    row = get_object_or_404(Payment.objects.select_related('order__primary_table','order__area','recorded_by','confirmed_by'),
        pk=payment_id,order__business_day=day,method__in=['TRANSFER','DEPOSIT'])
    error = ''
    if request.method=='POST':
        try:
            services.review_payment(request,day.pk,row.pk,request.POST.get('action'))
            return redirect('management:payment',day_id=day.pk,payment_id=row.pk)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
    row.refresh_from_db(); day.refresh_from_db()
    revision = services.payment_revision(row,day)
    return page(request,'payment',{'day':day,'payment':row,'error':error,
        'can_confirm':request.user.has_perm('payments.verify_transfer_payment'),
        'can_reject':request.user.has_perm('payments.reject_transfer_payment'),
        'confirm_token':security.confirmation(request,'confirm',row.pk,revision),
        'reject_token':security.confirmation(request,'reject',row.pk,revision)},status=409 if error else 200)


@require_GET
@security.required
def print_jobs(request):
    from apps.printing.views import history_data
    if not (request.user.has_perm('printing.view_printjob') or request.user.has_perm('printing.manage_printers')):
        raise PermissionDenied
    data = history_data(request,request.user)
    if not request.user.has_perm('printing.manage_printers'):
        data['can_retry'] = data['can_reprint'] = False
    return page(request,'print_jobs',data,section='impresiones')


@require_POST
@security.required
def print_action(request, pk, action):
    from apps.printing.views import change_job
    from apps.printing.models import PrintJob
    security.require(request.user,'printing.manage_printers')
    try:
        change_job(request,request.user,get_object_or_404(PrintJob,pk=pk),action)
    except ValidationError as exc:
        return page(request,'message',{'error':' '.join(exc.messages)},status=409)
    return redirect(reverse('management:print-jobs')+'?status=all')


@require_GET
@security.required
def order_pending(request, pk):
    from apps.orders.models import TableOrder
    order = get_object_or_404(TableOrder.objects.select_related('responsible_waiter', 'primary_table', 'area', 'cash_session__register'), pk=pk)
    return page(request, 'order_pending', {'order': order, 'lines': order.lines.exclude(status='CANCELLED')}, section='cierres')
