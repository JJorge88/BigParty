"""Consulta agregada exclusiva del propietario; sin controles operativos."""
from django.db import transaction
from django.db.models import Sum
from . import report_queries as queries
from .report_views import period_form
from .views import page


def bars(title, values):
    rows = [{'label': label, 'amount': amount, 'display': queries.money(amount)} for label, amount in values]
    ceiling = max((abs(row['amount']) for row in rows), default=1) or 1
    for row in rows:
        row['width'] = round(float(abs(row['amount']) / ceiling) * 600)
    return {'title': title, 'rows': rows}


def dashboard(request):
    form = period_form(request)
    data = {'form': form, 'charts': []}
    if form.is_valid():
        with transaction.atomic():
            period = queries.Period(form.cleaned_data)
            totals = queries.commercial_totals(period)
            data['period'] = period
            data['charts'].append(bars('Ventas y cobros', [
                ('Ventas netas', totals['net']), ('Cobros confirmados netos', totals['confirmed']),
                ('Cobros pendientes', totals['pending'])]))
            for title, field in [('Productos más vendidos · importe neto', 'product_name_snapshot'),
                                 ('Ventas netas por área', 'order__area__name')]:
                rows = queries.lines(period).order_by().values(field).annotate(
                    gross_total=Sum('gross'), adjustments=Sum('adjusted'), refunds=Sum('refunded')).order_by('-gross_total')[:10]
                data['charts'].append(bars(title, [(row[field] or 'Sin nombre',
                    row['gross_total'] - row['adjustments'] - row['refunds']) for row in rows]))
    return page(request, 'owner_dashboard', data, status=200 if form.is_valid() else 400)
