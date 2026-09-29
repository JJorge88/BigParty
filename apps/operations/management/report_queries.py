"""Lecturas agregadas. Ventas y cobros pertenecen a la jornada de su pedido.
Reservas/eventos sin FK a jornada se agrupan por su fecha programada local.
"""
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Sum, Count, F, Q, OuterRef, Subquery, DecimalField, Value, ExpressionWrapper
from django.db.models.functions import Coalesce
from django.utils import timezone
from apps.cash.models import BusinessDay, CashSession, CashMovement, CashHandoff
from apps.orders.models import TableOrder, OrderLine, OrderActivity, OrderTableLink
from apps.payments.models import Payment, PaymentRefund, OrderAdjustment, AdjustmentAllocation, RefundAllocation
from apps.reservations.models import Reservation, ReservationPayment, ReservationCreditAllocation
from apps.events.models import Event, EventTicket, EventPurchasePayment
from apps.core.configuration import business
from apps.core.models import BusinessSettings

ZERO = Decimal('0.00')
LIMIT = 5000
MONEY = DecimalField(max_digits=20, decimal_places=2)
REPORTS = {'jornada': ('Resumen de jornada', 'Ventas, cobros y resultados de la operación.'),
           'productos': ('Ventas por producto', 'Productos y combos vendidos; ajustes atribuibles.'),
           'areas': ('Ventas por área', 'Mesas y ventas rápidas en cada área.'),
           'meseros': ('Actividad por mesero', 'Responsabilidad comercial, cobros y entregas.'),
           'cajas': ('Resultados de caja', 'Aperturas, retiros, conteos y diferencias.'),
           'pagos': ('Métodos de pago', 'Confirmados, pendientes, rechazados y reembolsos.'),
           'cancelaciones': ('Cancelaciones y reembolsos', 'Motivos, responsables y devolución de inventario.'),
           'ajustes': ('Descuentos y cortesías', 'Ajustes autorizados sobre el consumo.'),
           'reservas': ('Reservas', 'Solicitudes, llegadas y anticipos por aplicación.'),
           'eventos': ('Eventos', 'Entradas, accesos e ingresos confirmados.')}


class PeriodForm(forms.Form):
    period = forms.ChoiceField(label='Periodo', choices=[('current', 'Jornada actual'), ('day', 'Jornada específica'), ('range', 'Rango de jornadas')])
    start = forms.DateField(label='Desde', required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    end = forms.DateField(label='Hasta', required=False, widget=forms.DateInput(attrs={'type': 'date'}))

    def clean(self):
        data = super().clean()
        if data.get('period') != 'current':
            if not data.get('start'):
                self.add_error('start', 'Selecciona una fecha comercial.')
            if data.get('period') == 'day':
                data['end'] = data.get('start')
            if not data.get('end'):
                self.add_error('end', 'Selecciona la fecha final.')
            if data.get('start') and data.get('end'):
                if not 0 <= (data['end'] - data['start']).days <= 92:
                    raise forms.ValidationError('Selecciona un rango ordenado de hasta 93 días.')
        return data


class Period:
    def __init__(self, cleaned):
        if cleaned['period'] == 'current':
            day = BusinessDay.objects.filter(status='OPEN').first()
            self.start = self.end = day.business_date if day else timezone.localdate()
            self.days = BusinessDay.objects.filter(pk=day.pk) if day else BusinessDay.objects.none()
            self.label = f'Jornada actual · {self.start:%d/%m/%Y}' if day else 'Sin jornada abierta'
        else:
            self.start, self.end = cleaned['start'], cleaned['end']
            self.days = BusinessDay.objects.filter(business_date__range=(self.start, self.end))
            self.label = f'{self.start:%d/%m/%Y}' if self.start == self.end else f'{self.start:%d/%m/%Y} al {self.end:%d/%m/%Y}'
        self.orders = TableOrder.objects.filter(business_day__in=self.days)
        self.payments = Payment.objects.filter(order__in=self.orders)
        self.zone = ZoneInfo(business().timezone)
        self.since = datetime.combine(self.start, time.min, self.zone)
        self.until = datetime.combine(self.end + timedelta(days=1), time.min, self.zone)


def money(value):
    return f'{business_symbol()}{value:,.2f}' if value is not None else '—'


def business_symbol():
    # Current supported currency is fixed GTQ; one centralized presentation constant.
    return BusinessSettingsSymbol


BusinessSettingsSymbol = BusinessSettings._meta.get_field('currency_symbol').default


def stamp(value):
    return timezone.localtime(value).strftime('%d/%m/%Y %H:%M') if value else '—'


def person(user):
    return (user.get_full_name() or user.username) if user else 'Sistema'


def total(qs, field='amount', **filters):
    return qs.filter(**filters).aggregate(v=Sum(field))['v'] or ZERO


def bounded(qs):
    rows = list(qs[:LIMIT + 1])
    if len(rows) > LIMIT:
        raise ValidationError('El reporte supera 5,000 filas. Reduce el periodo solicitado.')
    return rows


def section(title, columns, rows):
    return dict(title=title, columns=columns, rows=rows)


def lines(period):
    adjustment = AdjustmentAllocation.objects.filter(order_line=OuterRef('pk')).order_by().values('order_line').annotate(v=Sum('amount')).values('v')
    refund = RefundAllocation.objects.filter(payment_allocation__order_line=OuterRef('pk')).order_by().values('payment_allocation__order_line').annotate(v=Sum('amount')).values('v')
    return OrderLine.objects.filter(order__in=period.orders, status='SENT').annotate(
        gross=ExpressionWrapper(F('quantity') * F('unit_price'), output_field=MONEY),
        adjusted=Coalesce(Subquery(adjustment, output_field=MONEY), Value(ZERO)),
        refunded=Coalesce(Subquery(refund, output_field=MONEY), Value(ZERO)))


def commercial_totals(period):
    aggregate = lines(period).aggregate(gross_sum=Sum('gross'), adjustments=Sum('adjusted'), refunds=Sum('refunded'))
    result = {'gross': aggregate['gross_sum'], 'adjustments': aggregate['adjustments'], 'refunds': aggregate['refunds']}
    result = {key: value or ZERO for key, value in result.items()}
    result['net'] = result['gross'] - result['adjustments'] - result['refunds']
    result['confirmed'] = total(period.payments, status__in=('CONFIRMED', 'REFUNDED')) - total(PaymentRefund.objects.filter(payment__in=period.payments))
    result['pending'] = total(period.payments, status='PENDING')
    result['credit'] = total(ReservationCreditAllocation.objects.filter(order_line__order__in=period.orders, order_line__status='SENT'))
    result['balance'] = result['net'] - result['confirmed'] - result['credit']
    return result


def products(period):
    qs = lines(period).order_by().values('product_id', 'product_name_snapshot', 'product__category__name').annotate(
        units=Sum('quantity'), sales=Sum('gross'), adjustment=Sum('adjusted'), refund=Sum('refunded')).order_by('-sales', 'product_id', 'product_name_snapshot')
    return section('Productos', ['Producto', 'Categoría actual', 'Cantidad', 'Bruto', 'Ajustes', 'Reembolsos', 'Neto'],
                   [[r['product_name_snapshot'], r['product__category__name'], r['units'], money(r['sales']), money(r['adjustment']), money(r['refund']), money(r['sales']-r['adjustment']-r['refund'])] for r in bounded(qs)])


def areas(period):
    amounts = {r['order__area_id']: r for r in lines(period).order_by().values('order__area_id').annotate(gross_sum=Sum('gross'), adjustment=Sum('adjusted'), refund=Sum('refunded'))}
    qs = period.orders.exclude(status='MERGED').order_by().values('area_id', 'area__name').annotate(count=Count('pk'), quick=Count('pk', filter=Q(order_type='QUICK_SALE'))).order_by('area__name')
    rows = []
    for row in bounded(qs):
        values = amounts.get(row['area_id'], {})
        gross, adj, refund = [values.get(k, ZERO) for k in ('gross_sum', 'adjustment', 'refund')]
        rows.append([row['area__name'], row['count'], row['quick'], money(gross), money(adj), money(refund), money(gross-adj-refund)])
    return section('Áreas', ['Área', 'Pedidos', 'Ventas rápidas', 'Bruto', 'Ajustes', 'Reembolsos', 'Neto'], rows)


def methods(period):
    counts = {(r['method'], r['status']): r for r in period.payments.order_by().values('method', 'status').annotate(v=Sum('amount'), n=Count('pk'))}
    refunds = {r['payment__method']: r['v'] for r in PaymentRefund.objects.filter(payment__in=period.payments).order_by().values('payment__method').annotate(v=Sum('amount'))}
    rows = []
    for code, label in Payment.Method.choices:
        confirmed = sum((counts.get((code, status), {}).get('v', ZERO) for status in ('CONFIRMED', 'REFUNDED')), ZERO)
        refunded = refunds.get(code, ZERO)
        rows.append([label, money(confirmed), money(counts.get((code, 'PENDING'), {}).get('v', ZERO)), money(counts.get((code, 'REJECTED'), {}).get('v', ZERO)), money(refunded), money(confirmed-refunded)])
    return section('Cobros por método', ['Método', 'Confirmado bruto', 'Pendiente', 'Rechazado', 'Reembolsado', 'Confirmado neto'], rows)


def waiters(period):
    amounts = {r['order__responsible_waiter_id']: r for r in lines(period).order_by().values('order__responsible_waiter_id').annotate(gross_sum=Sum('gross'), adjustment=Sum('adjusted'), refund=Sum('refunded'))}
    names = ('responsible_waiter_id', 'responsible_waiter__first_name', 'responsible_waiter__last_name', 'responsible_waiter__username')
    qs = period.orders.exclude(status='MERGED').order_by().values(*names).annotate(n=Count('pk', distinct=True), tables=Count('table_links__table_id', distinct=True)).order_by('responsible_waiter_id')
    rows = []
    for r in bounded(qs):
        v = amounts.get(r['responsible_waiter_id'], {})
        gross, adj, refund = [v.get(k, ZERO) for k in ('gross_sum', 'adjustment', 'refund')]
        name = ' '.join(filter(None, [r['responsible_waiter__first_name'], r['responsible_waiter__last_name']])) or r['responsible_waiter__username'] or 'Sin responsable'
        rows.append([name, r['n'], r['tables'], money(gross), money(gross-adj-refund)])
    by_actor = period.payments.filter(status__in=('CONFIRMED', 'REFUNDED')).order_by().values('recorded_by_id', 'recorded_by__username').annotate(v=Sum('amount')).order_by('recorded_by_id')
    actor_refunds = {r['payment__recorded_by_id']: r['v'] for r in PaymentRefund.objects.filter(payment__in=period.payments).order_by().values('payment__recorded_by_id').annotate(v=Sum('amount'))}
    handoffs = CashHandoff.objects.filter(payment__in=period.payments).order_by().values('waiter__username').annotate(delivered=Sum('amount', filter=Q(status='DELIVERED')), pending=Sum('amount', filter=Q(status='PENDING'))).order_by('waiter__username')
    return [section('Responsabilidad comercial', ['Mesero responsable', 'Pedidos', 'Mesas', 'Bruto asociado', 'Neto asociado'], rows),
            section('Cobros registrados por usuario', ['Usuario que registró', 'Confirmado bruto', 'Reembolsos', 'Confirmado neto'], [[r['recorded_by__username'], money(r['v']), money(actor_refunds.get(r['recorded_by_id'], ZERO)), money(r['v']-actor_refunds.get(r['recorded_by_id'], ZERO))] for r in bounded(by_actor)]),
            section('Entregas de efectivo', ['Mesero', 'Entregado', 'Pendiente'], [[r['waiter__username'], money(r['delivered'] or ZERO), money(r['pending'] or ZERO)] for r in bounded(handoffs)])]


def cash(period):
    qs = CashSession.objects.filter(business_day__in=period.days).select_related('register', 'cashier', 'business_day').annotate(
        incoming=Coalesce(Sum('movements__amount', filter=Q(movements__movement_type__in=('DIRECT_CASH_PAYMENT', 'WAITER_HANDOFF'))), ZERO),
        withdrawals=Coalesce(Sum('movements__amount', filter=Q(movements__movement_type='WITHDRAWAL')), ZERO),
        returns=Coalesce(Sum('movements__amount', filter=Q(movements__movement_type='CASH_REFUND')), ZERO),
        handoffs_total=Coalesce(Sum('movements__amount', filter=Q(movements__movement_type='WAITER_HANDOFF')), ZERO)).order_by('-opened_at', '-pk')
    return section('Sesiones de caja', ['Caja / cajero', 'Jornada', 'Apertura / cierre', 'Fondo', 'Esperado', 'Contado', 'Diferencia', 'Retiros', 'Entregas', 'Estado'],
        [[f'{s.register.name} / {person(s.cashier)}', str(s.business_day.business_date), stamp(s.opened_at)+' / '+stamp(s.closed_at), money(s.opening_float), money(s.opening_float+s.incoming-s.withdrawals-s.returns), money(s.counted_cash if s.status=='CLOSED' else None), money(s.difference if s.status=='CLOSED' else None), money(s.withdrawals), money(s.handoffs_total), s.get_status_display()] for s in bounded(qs)])


def adjustments(period):
    qs = OrderAdjustment.objects.filter(order__in=period.orders).select_related('order__primary_table', 'subaccount', 'authorized_by').order_by('-created_at', '-pk')
    return section('Ajustes autorizados', ['Fecha', 'Pedido / mesa', 'Subcuenta', 'Tipo', 'Importe', 'Motivo', 'Autorizó'],
        [[stamp(r.created_at), f'#{r.order_id} · {r.order.display_name}', r.subaccount.name if r.subaccount else 'Cuenta general', r.get_adjustment_type_display(), money(r.amount), r.reason, person(r.authorized_by)] for r in bounded(qs)])


def cancellations(period):
    from apps.inventory.models import InventoryMovement
    cancelled = bounded(OrderActivity.objects.filter(order__in=period.orders, activity_type='LINE_CANCELLED').select_related('order__primary_table', 'user').order_by('-created_at', '-pk'))
    ids = [r.metadata.get('line_id') for r in cancelled if isinstance(r.metadata.get('line_id'), int)]
    line_map = {r.pk: r for r in OrderLine.objects.filter(pk__in=ids)}
    returned_ids = set(InventoryMovement.objects.filter(movement_type='CANCELLATION_RETURN', metadata__line_id__in=ids).values_list('metadata__line_id', flat=True))
    cancelled_orders = [r.order_id for r in cancelled if r.metadata.get('sale_cancelled')]
    sale_amounts = {r['order_id']: r['amount'] for r in OrderLine.objects.filter(order_id__in=cancelled_orders, status='CANCELLED').order_by().values('order_id').annotate(amount=Sum(F('quantity')*F('unit_price')))}
    returned_orders = set(InventoryMovement.objects.filter(movement_type='CANCELLATION_RETURN', metadata__order_id__in=cancelled_orders).values_list('metadata__order_id', flat=True))
    rows = []
    for r in cancelled:
        line = line_map.get(r.metadata.get('line_id'))
        amount = line.quantity * line.unit_price if line else sale_amounts.get(r.order_id)
        returned = (line and line.pk in returned_ids) or r.order_id in returned_orders
        kind = 'Venta rápida anulada' if r.metadata.get('sale_cancelled') else ('Producto enviado anulado' if r.metadata.get('reason') else 'Borrador retirado')
        rows.append([stamp(r.created_at), f'#{r.order_id} · {r.order.display_name}', line.product_name_snapshot if line else 'Pedido', kind, money(amount), r.metadata.get('reason') or r.description, person(r.user), 'Sí' if returned else 'No'])
    refunds = PaymentRefund.objects.filter(payment__in=period.payments).select_related('payment__order__primary_table', 'created_by').order_by('-created_at', '-pk')
    refund_rows = [[stamp(r.created_at), f'#{r.payment.order_id} · {r.payment.order.display_name}', 'Pago #'+str(r.payment_id), 'Reembolso', money(r.amount), r.reason, person(r.created_by), 'Sí' if r.return_to_inventory else 'No'] for r in bounded(refunds)]
    columns = ['Fecha', 'Pedido / mesa', 'Producto / pago', 'Tipo', 'Importe', 'Motivo', 'Usuario', 'Devolución inventario']
    return [section('Cancelaciones · importe informativo, no es una devolución de dinero', columns, rows), section('Reembolsos efectivos', columns, refund_rows)]


def reservations(period):
    qs = Reservation.objects.filter(reservation_date__range=(period.start, period.end))
    status = {r['status']:r['n'] for r in qs.order_by().values('status').annotate(n=Count('pk'))}
    payments = ReservationPayment.objects.filter(reservation__in=qs, status='CONFIRMED')
    return [section('Reservas por fecha programada local', ['Estado', 'Cantidad'], [['Solicitudes totales', qs.count()]] + [[label, status.get(code, 0)] for code,label in Reservation.Status.choices]),
            section('Anticipos confirmados · separados de los cobros de consumo', ['Aplicación', 'Confirmado'], [['Abono al consumo', money(total(payments, reservation__payment_application='CREDIT'))], ['Cargo de reserva', money(total(payments, reservation__payment_application='FEE'))]])]


def events(period):
    qs = Event.objects.filter(starts_at__gte=period.since, starts_at__lt=period.until).order_by('starts_at', 'pk')
    tickets = {r['event_id']:r for r in EventTicket.objects.filter(event__in=qs).order_by().values('event_id').annotate(
        sold=Count('pk', filter=Q(purchase__isnull=False, table_reservation__isnull=True)),
        courtesy=Count('pk', filter=Q(purchase__isnull=True)), tables=Count('pk', filter=Q(table_reservation__isnull=False)), used=Count('pk', filter=Q(used_at__isnull=False)))}
    paid = {r['purchase__event_id']:r for r in EventPurchasePayment.objects.filter(purchase__event__in=qs).order_by().values('purchase__event_id').annotate(confirmed=Sum('amount', filter=Q(status='CONFIRMED')), pending=Sum('amount', filter=Q(status='PENDING')))}
    rows = []
    for e in bounded(qs):
        t, p = tickets.get(e.pk, {}), paid.get(e.pk, {})
        rows.append([e.name, stamp(e.starts_at), e.maximum_capacity, t.get('sold',0), t.get('courtesy',0), t.get('tables',0), t.get('used',0), money(p.get('confirmed') or ZERO), money(p.get('pending') or ZERO)])
    return section('Eventos por fecha programada local', ['Evento', 'Fecha', 'Capacidad', 'Vendidas', 'Cortesías', 'Accesos mesa', 'Usadas', 'Confirmado', 'Por verificar'], rows)


def build(kind, period):
    sections, kpis = [], []
    if kind == 'jornada':
        values = commercial_totals(period)
        kpis = [(label, money(values[key])) for key, label in [('gross','Venta bruta'), ('adjustments','Ajustes'), ('refunds','Reembolsos'), ('net','Consumo neto'), ('confirmed','Cobros confirmados netos'), ('pending','Pagos por verificar'), ('credit','Abonos de reserva aplicados'), ('balance','Saldo por cobrar')]]
        tables = OrderTableLink.objects.filter(order__in=period.orders).values('table_id').distinct().count()
        kpis.append(('Mesas atendidas', str(tables)))
        sections = [methods(period), areas(period), products(period), cash(period), *cancellations(period), adjustments(period), *reservations(period), events(period)]
        sections[2]['rows'] = sections[2]['rows'][:20]
        sections[2]['title'] = '20 productos principales por venta bruta'
    elif kind == 'productos': sections = [products(period)]
    elif kind == 'areas': sections = [areas(period)]
    elif kind == 'meseros': sections = waiters(period)
    elif kind == 'cajas': sections = [cash(period)]
    elif kind == 'pagos': sections = [methods(period)]
    elif kind == 'cancelaciones': sections = cancellations(period)
    elif kind == 'ajustes': sections = [adjustments(period)]
    elif kind == 'reservas': sections = reservations(period)
    elif kind == 'eventos': sections = [events(period)]
    return {'title': REPORTS[kind][0], 'description': REPORTS[kind][1], 'sections': sections, 'kpis': kpis}
