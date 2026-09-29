"""Presentación de Gerencia: consume consultas financieras, no altera sus reglas."""
from django.conf import settings
from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from django.db.models import OuterRef, Subquery, Q
from django.urls import reverse
from django.utils import timezone
from apps.cash import queries as cash
from apps.cash.models import BusinessDay, CashRegister, CashSession
from apps.orders.models import OrderTableLink, ACTIVE_STATUSES
from apps.payments.models import Payment
from apps.payments.queries import get_financial_summary
from apps.printing.models import PrintJob
from . import security

ZERO = Decimal('0.00')


def current_day():
    return BusinessDay.objects.filter(status='OPEN').first()


def base(request, section):
    user = request.user
    name = user.get_full_name().strip() or user.username
    return {'section':section, 'operator_name':name, 'operator_role':user.get_role_display(),
        'initials':''.join(part[0] for part in name.split()[:2]).upper(),
        'can_financial':security.financial(user), 'can_payments':security.can_review(user),
        'can_open':user.has_perm('cash.open_business_day'), 'can_close':user.has_perm('cash.close_business_day'),
        'can_reopen':user.has_perm('cash.reopen_business_day'),
        'idle_timeout':settings.MANAGEMENT_IDLE_TIMEOUT_SECONDS}


def payment_methods(payments):
    """Cobros netos por método; misma semántica del resumen de caja/jornada."""
    from apps.payments.queries import summarize_payment_methods
    return summarize_payment_methods(payments)


def method_rows(methods):
    total = sum((row['confirmed_net'] for row in methods.values()),ZERO)
    return [{'code':key, 'name':Payment.Method(key).label, **row,
        'percent':float(row['confirmed_net'] / total * 100) if total else 0}
        for key,row in methods.items()]


def chart(points):
    values = [value for _,value in points]
    ceiling = max(values, default=ZERO) or Decimal('1')
    n = len(points)
    plotted = [{'label':label, 'value':value, 'x':round(30 + i * 700 / max(1,n-1),2),
        'y':round(158-float(value/ceiling)*130,2)} for i,(label,value) in enumerate(points)]
    path = ' '.join(f'{p["x"]},{p["y"]}' for p in plotted)
    return {'points':plotted, 'line':path, 'fill':f'30,158 {path} {plotted[-1]["x"]},158' if plotted else '',
        'max':ceiling, 'has_data':bool(points), 'ticks':[p for i,p in enumerate(plotted) if i in {0,n//4,n//2,3*n//4,n-1}]}


def blocker_rows(blockers, day, user):
    financial = security.financial(user)
    rows = []
    for blocker in blockers:
        kind, pk = blocker['type'], blocker['object_id']
        description = blocker['description']
        if not financial and kind == 'OUTSTANDING_BALANCE':
            description = f'Pedido #{pk}: saldo pendiente.'
        url = ''
        if kind == 'PENDING_PAYMENT' and security.can_review(user):
            url = reverse('management:payment',args=[day.pk,pk])
        elif kind == 'OPEN_CASH_SESSION':
            url = reverse('management:cash-detail',args=[day.pk,pk])
        rows.append({**blocker,'description':description,'url':url})
    return rows


def register_cards(day, sessions):
    latest = {}
    for session in sessions:
        latest.setdefault(session.register_id,session)
    closed = CashSession.objects.filter(register_id=OuterRef('pk'),status='CLOSED').order_by('-closed_at','-pk')
    registers = CashRegister.objects.select_related('area').filter(is_active=True).annotate(last_close=Subquery(closed.values('closed_at')[:1]))
    registers = registers.order_by('area__sort_order','pk')
    rows = []
    for register in registers:
        session = latest.get(register.pk)
        rows.append({'name':register.name,'area':register.area.name,'session':session,'last_close':register.last_close,
            'url':reverse('management:cash-detail',args=[day.pk,session.pk]) if day and session else ''})
    return rows


def day_data(day, user, *, with_blockers=True):
    snapshot = cash.get_business_day_snapshot(day)
    summary = cash.get_business_day_summary(day,snapshot=snapshot)
    blockers = cash.get_business_day_close_blockers(day,snapshot=snapshot) if with_blockers and day.status == 'OPEN' else []
    failures_query = PrintJob.objects.filter(order__business_day=day,status='FAILED')
    failures = list(failures_query.select_related('order__primary_table','printer').order_by('created_at')[:20])
    failure_count = failures_query.count()
    print_url = reverse('management:print-jobs') if user.has_perm('printing.view_printjob') or user.has_perm('printing.manage_printers') else ''
    incidents = [{'description':f'Impresión #{job.pk} fallida · {job.order.display_name}', 'url':print_url} for job in failures]
    for session in snapshot['sessions']:
        if session.status == 'CLOSED' and session.difference:
            description = f'{session.register.name}: diferencia registrada.'
            if security.financial(user):
                result = 'Faltante' if session.difference < ZERO else 'Sobrante'
                description = f'{session.register.name}: {result} Q{abs(session.difference)}. {session.closing_reason}'
            incidents.append({'description':description, 'url':reverse('management:cash-detail',args=[day.pk,session.pk])})
    return {'day':day,'snapshot':snapshot,'summary':summary,'methods':method_rows(summary['payments_by_method']),
        'session_rows':[{'session':s, 'financial':cash.get_cash_session_summary(s)} for s in snapshot['sessions']],
        'failures':failures,'failure_count':failure_count,'incidents':incidents,'print_url':print_url,
        'blockers':blocker_rows(blockers,day,user),'registers':register_cards(day,snapshot['sessions'])}


def dashboard(day, user):
    data = day_data(day,user)
    snapshot = data['snapshot']
    pending = [p for p in snapshot['payments'] if p.status=='PENDING' and p.method in ('TRANSFER','DEPOSIT')]
    failures, failure_count = data['failures'], data['failure_count']
    important = [b for b in data['blockers'] if b['type'] in ('PENDING_HANDOFF','FINANCIAL_INCONSISTENCY','CASH_INCONSISTENCY','UNASSIGNED_LEGACY_ORDER')]
    # Una inconsistencia puede describirse varias veces: atención cuenta entidades distintas.
    important = list({(b['type'],b['object_id']):b for b in important}.values())
    attention = []
    for payment in pending:
        attention.append({'title':payment.get_method_display()+' pendiente', 'detail':payment.order.display_name,
            'amount':payment.amount if security.can_review(user) else None,
            'url':reverse('management:payment',args=[day.pk,payment.pk]) if security.can_review(user) else ''})
    for job in failures:
        attention.append({'title':'Impresión fallida', 'detail':f'{job.payload_snapshot.get("destination","Impresora")} · {job.order.display_name}',
            'url':reverse('management:print-jobs') if user.has_perm('printing.view_printjob') or user.has_perm('printing.manage_printers') else ''})
    attention += [{'title':'Pendiente operativo','detail':b['description'],'url':b['url']} for b in important]
    totals = defaultdict(lambda: ZERO)
    for order in snapshot['orders']:
        totals[(order.area_id,order.area.name,order.area.sort_order)] += get_financial_summary(order)['charge_total']
    from apps.venues.models import Area
    areas = list(Area.objects.filter(Q(is_active=True) | Q(pk__in=[key[0] for key in totals])).order_by('sort_order','pk'))
    max_area = max(totals.values(),default=ZERO) or Decimal('1')
    area_rows = [{'name':a.name,'total':totals[(a.pk,a.name,a.sort_order)],
        'percent':float(totals[(a.pk,a.name,a.sort_order)]/max_area*100)} for a in areas]
    hourly = defaultdict(lambda: ZERO)
    for payment in snapshot['payments']:
        if payment.status in ('CONFIRMED','REFUNDED'):
            hour = timezone.localtime(payment.confirmed_at).replace(minute=0,second=0,microsecond=0)
            hourly[hour] += payment.amount - sum((r.amount for r in payment.refunds.all()),ZERO)
    points = []
    if hourly:
        hour, last_hour = min(hourly), max(hourly)
        while hour <= last_hour:
            points.append((hour.strftime('%d/%m %H:00'), hourly[hour]))
            hour += timedelta(hours=1)
    data.update(occupied_tables=OrderTableLink.objects.filter(order__business_day=day,order__status__in=ACTIVE_STATUSES,
        released_at__isnull=True).values('table_id').distinct().count(),
        pending_count=len(pending)+failure_count+len(important), attention=attention[:5], attention_count=len(attention),
        areas=area_rows, hourly=chart(points),confirmed_net=sum((m['confirmed_net'] for m in data['methods']),ZERO))
    return data


def cash_detail(day, session, user):
    # Sin permiso financiero no cargar/importar importes a la presentación.
    result = {'day':day,'cash_session':session,'financial':None,'movements':[], 'pending_handoffs':[], 'methods':[]}
    if not security.financial(user):
        return result
    snapshot = cash.get_business_day_snapshot(day)
    prepared = next(s for s in snapshot['sessions'] if s.pk==session.pk)
    result['financial'] = cash.get_cash_session_summary(prepared)
    income_ids = {m.payment_id for m in prepared._ledger_movements if m.movement_type in cash.INCOMING}
    associated = [p for p in snapshot['payments'] if p.order.cash_session_id==session.pk or p.pk in income_ids]
    methods = method_rows(payment_methods(associated))
    result.update(methods=methods,associated_sales=sum((row['confirmed_net'] for row in methods),ZERO),
        movements=list(reversed(prepared._ledger_movements))[:30],
        pending_handoffs=list(cash.get_pending_cash_handoffs(day=day).filter(payment__order__area=session.register.area)[:20]),
        difference_amount=abs(session.difference) if session.difference is not None else ZERO)
    return result
