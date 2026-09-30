from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import connection, transaction
from django.http import Http404, HttpResponse
from django.utils.text import slugify
from django.views.decorators.http import require_GET
from . import security, report_queries as queries
from .views import page


def period_form(request):
    data = request.GET.copy()
    if not data.get('period'):
        data['period'] = 'current'
    return queries.PeriodForm(data)


@require_GET
@security.required
def hub(request):
    security.require(request.user, 'core.view_reports')
    form = period_form(request)
    valid = form.is_valid()
    period = queries.Period(form.cleaned_data) if valid else None
    params = request.GET.copy(); params.pop('page', None)
    return page(request, 'reports', dict(form=form, period=period, report_cards=[dict(code=code, title=title, description=description) for code,(title,description) in queries.REPORTS.items()], filter_query=params.urlencode()), section='reportes')


@require_GET
@security.required
def report(request, kind, pdf=False):
    security.require(request.user, 'core.view_reports')
    if pdf:
        security.require(request.user, 'core.export_reports_pdf')
    if kind not in queries.REPORTS:
        raise Http404
    form = period_form(request)
    data = dict(form=form, kind=kind, title=queries.REPORTS[kind][0], error='', sections=[], kpis=[])
    status = 200
    if form.is_valid():
        try:
            # All component aggregates see the same committed snapshot.
            with transaction.atomic():
                # Tests may wrap the view in their own transaction. Production requests do not.
                if connection.vendor == 'postgresql' and len(connection.atomic_blocks) == 1:
                    with connection.cursor() as cursor:
                        cursor.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
                period = queries.Period(form.cleaned_data)
                data.update(queries.build(kind, period), period=period)
                if pdf:
                    from .report_pdf import generate
                    try:
                        content = generate(data, period, request.user)
                    except ValidationError:
                        raise
                    except Exception:
                        import logging
                        logging.getLogger('apps.hardening').error('pdf_failed',extra={'support_reference':getattr(request,'support_reference','')})
                        raise ValidationError('No se pudo generar el PDF. Intenta nuevamente o reduce el periodo.') from None
                    dates = str(period.start) if period.start == period.end else f'{period.start}-a-{period.end}'
                    filename = slugify(f'big-party-{kind}-{dates}') + '.pdf'
                    response = HttpResponse(content, content_type='application/pdf')
                    response['Content-Disposition'] = f'attachment; filename="{filename}"'
                    response['X-Content-Type-Options'] = 'nosniff'
                    return response
            for section in data['sections']:
                section['page'] = Paginator(section['rows'], 25).get_page(request.GET.get('page'))
        except ValidationError as exc:
            data.update(error=' '.join(exc.messages), sections=[], kpis=[])
            status = 400
    else:
        status = 400
    params = request.GET.copy(); params.pop('page', None)
    data['filter_query'] = params.urlencode()
    return page(request, 'report', data, section='reportes', status=status)
