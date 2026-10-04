from apps.core.configuration import bank as transfer_bank
from apps.core import public_site as site
from apps.core.public_forms import GuestForm
from urllib.parse import urlencode
from django.conf import settings
from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET
from apps.operations.management import security
from apps.operations.management.queries import base
from .models import Event, EventTicketType, EventPurchase, EventTicket, EventTableConfiguration
from . import services, queries
from .forms import EventForm, TicketTypeForm, TableForm, PaymentForm, SettingsForm, RescheduleForm


def page(request, template, data):
    return render(request, 'events/' + template, {**base(request, 'eventos'), **data})


def private(response):
    response['Cache-Control'] = 'no-store, private'
    response['Referrer-Policy'] = 'same-origin'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def error_text(exc):
    return ' '.join(exc.messages)


@security.required
@require_GET
def index(request):
    services.require(request.user, 'view_events')
    all_events = Event.objects.all()
    rows = all_events
    selected = request.GET.get('filter', '')
    filters = [('', 'Todos'), ('PUBLISHED', 'Publicados'), ('DRAFT', 'Borradores'), ('FINISHED', 'Finalizados'), ('CANCELLED', 'Cancelados')]
    if selected == 'PUBLISHED':
        rows = rows.filter(status__in=queries.LIVE_STATUSES)
    elif selected in dict(filters) and selected:
        rows = rows.filter(status=selected)
    search = request.GET.get('q', '').strip()[:140]
    if search:
        rows = rows.filter(Q(name__icontains=search) | Q(artist_name__icontains=search))
    counts = {'published': all_events.filter(status__in=queries.LIVE_STATUSES).count(),
        'upcoming': all_events.filter(status__in=queries.LIVE_STATUSES, starts_at__gt=timezone.now()).count(),
        'draft': all_events.filter(status='DRAFT').count()}
    if request.user.has_perm('events.view_event_capacity'):
        counts['sold'] = EventTicket.objects.filter(purchase__isnull=False).count()
    return page(request, 'list.html', dict(rows=Paginator(rows, 24).get_page(request.GET.get('page')), counts=counts, filters=filters, selected=selected, search=search))


@security.required
@require_http_methods(['GET', 'POST'])
def wizard(request, pk=None, step=1):
    if step not in (1, 2, 3, 4):
        raise Http404
    permission = {1: 'change_event' if pk else 'create_event', 2: 'manage_event_ticket_types', 3: 'manage_event_tables', 4: 'view_events'}[step]
    services.require(request.user, permission)
    event = get_object_or_404(Event, pk=pk) if pk else None
    error = ''
    type_row = get_object_or_404(EventTicketType, pk=request.GET['type'], event=event) if step == 2 and request.GET.get('type', '').isdigit() else None
    form = None
    if step == 1:
        form = EventForm(request.POST or None, request.FILES or None, instance=event)
    elif step == 2:
        form = TicketTypeForm(request.POST or None, instance=type_row, initial={'sale_starts_at': timezone.localtime().replace(second=0, microsecond=0), 'sale_ends_at': event.starts_at})
    elif step == 3:
        form = TableForm(request.POST if request.POST.get('action') == 'table' else None, event=event)
    if request.method == 'POST':
        try:
            if step == 1 and form.is_valid():
                # ModelForm cambia instance antes de guardar: el servicio recarga y compara con DB.
                event = services.edit_event(event, request.user, **form.cleaned_data) if pk else services.create_event(request.user, **form.cleaned_data)
                messages.success(request, 'Información guardada. Continúa con los tipos de entrada.')
                return redirect('events:wizard', pk=event.pk, step=2)
            if step == 2 and form.is_valid():
                services.save_ticket_type(event, request.user, type_row, **form.cleaned_data)
                messages.success(request, 'Tipo de entrada guardado. Puedes agregar otro o continuar a mesas y aforo.')
                return redirect('events:wizard', pk=event.pk, step=2)
            if step == 3:
                if request.POST.get('action') == 'capacity':
                    try:
                        capacity = int(request.POST.get('maximum_capacity', ''))
                    except ValueError:
                        raise ValidationError('Aforo inválido.')
                    services.edit_event(event, request.user, maximum_capacity=capacity)
                    messages.success(request, 'Aforo guardado. Continúa con la revisión del evento.')
                    return redirect('events:wizard', pk=event.pk, step=3)
                if form.is_valid():
                    services.save_event_table(event, request.user, **form.cleaned_data)
                    messages.success(request, 'Mesa del evento guardada.')
                    return redirect('events:wizard', pk=event.pk, step=3)
            if step == 4:
                if request.POST.get('action') == 'publish':
                    services.publish_event(event, request.user)
                return redirect('events:detail', pk=event.pk)
        except ValidationError as exc:
            error = error_text(exc)
    if event and event.pk:
        event.refresh_from_db()
    return page(request, 'wizard.html', dict(event=event, step=step, steps=[(1,'Información'), (2,'Entradas'), (3,'Mesas y aforo'), (4,'Revisar y publicar')],
        form=form, error=error, types=queries.ticket_type_rows(event) if event else [], tables=queries.table_rows(event) if event else [],
        pool=queries.configuration_summary(event) if event else {}, validation=services.validate_event_for_publication(event) if event else []))


@security.required
@require_http_methods(['GET', 'POST'])
def configure(request):
    services.require(request.user, 'change_event')
    form = SettingsForm(request.POST or None, instance=queries.get_settings())
    error = ''
    if request.method == 'POST' and form.is_valid():
        try:
            services.configure_settings(request.user, **form.cleaned_data)
            return redirect('events:list')
        except ValidationError as exc:
            error = error_text(exc)
    return page(request, 'settings.html', dict(form=form, error=error))


@security.required
@require_http_methods(['GET', 'POST'])
def detail(request, pk):
    services.require(request.user, 'view_events')
    event = get_object_or_404(Event, pk=pk)
    error, issued = '', []
    reschedule_form = RescheduleForm(request.POST if request.POST.get('action') == 'reschedule' else None)
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            if action == 'duplicate':
                copy = services.duplicate_event(event, request.user)
                return redirect('events:wizard', pk=copy.pk, step=1)
            if request.POST.get('confirmed') != 'yes':
                raise ValidationError('Confirma la acción antes de continuar.')
            if action == 'cancel':
                services.cancel_event(event, request.user, request.POST.get('reason', '')[:2000])
            elif action == 'finish':
                services.finish_event(event, request.user)
            elif action == 'reschedule':
                if not reschedule_form.is_valid():
                    raise ValidationError('Revisa las nuevas fechas y el motivo.')
                services.reschedule_event(event, request.user, **reschedule_form.cleaned_data)
            elif action == 'courtesy':
                kind = get_object_or_404(EventTicketType, pk=request.POST.get('ticket_type') if request.POST.get('ticket_type', '').isdigit() else None, event=event)
                quantity = int(request.POST.get('quantity', '0')) if request.POST.get('quantity', '').isdigit() else 0
                services.issue_courtesy_tickets(event, kind, quantity, request.user, request.POST.get('reason', '')[:2000])
                return redirect(reverse('events:detail', args=[pk]) + '?courtesias=1')
            else:
                raise ValidationError('Acción desconocida.')
            if not issued:
                return redirect('events:detail', pk=pk)
        except ValidationError as exc:
            error = error_text(exc)
        event.refresh_from_db()
    can_capacity = request.user.has_perm('events.view_event_capacity')
    tables = queries.table_rows(event) if can_capacity else []
    return page(request, 'detail.html', dict(event=event, publication_checks=services.validate_event_for_publication(event) if event.status == 'DRAFT' else [], error=error, issued=event.tickets.filter(purchase__isnull=True).select_related('ticket_type').order_by('-pk')[:30] if request.user.has_perm('events.issue_courtesy_tickets') else [], reschedule_form=reschedule_form,
        capacity=queries.get_event_capacity_summary(event) if can_capacity else None,
        sold_count=event.tickets.filter(purchase__isnull=False).count() if can_capacity else None,
        types=queries.ticket_type_rows(event) if can_capacity else [], tables=tables[:5],
        table_count=len([t for t in tables if t.enabled]), table_available=len([t for t in tables if t.available]),
        table_reserved=len([t for t in tables if t.enabled and not t.available]),
        table_capacity=sum(t.capacity_snapshot for t in tables if t.enabled),
        courtesy_types=event.ticket_types.filter(is_active=True, is_courtesy_type=True),
        current_types=[t for t in queries.ticket_type_rows(event) if t.sellable] if can_capacity else []))


@security.required
@require_GET
def purchases(request, pk):
    services.require(request.user, 'view_event_purchases')
    event = get_object_or_404(Event, pk=pk)
    rows = event.purchases.select_related('payment').order_by('-created_at')
    selected = request.GET.get('filter', '')
    filters = [('', 'Todas'), ('PENDING_PAYMENT', 'Esperando pago'), ('PAYMENT_REVIEW', 'Por verificar'), ('CONFIRMED', 'Confirmadas'), ('REJECTED', 'Rechazadas')]
    if selected in dict(filters) and selected:
        rows = rows.filter(status=selected)
    return page(request, 'purchases.html', dict(event=event, rows=Paginator(rows, 30).get_page(request.GET.get('page')), filters=filters, selected=selected))


@security.required
@require_http_methods(['GET', 'POST'])
def purchase_review(request, code):
    services.require(request.user, 'view_event_purchases')
    purchase = get_object_or_404(EventPurchase.objects.select_related('event', 'payment'), public_code=code)
    error = ''
    if request.method == 'POST':
        try:
            action = request.POST.get('action')
            security.verify_confirmation(request, action, code, purchase.updated_at.isoformat())
            payment = getattr(purchase, 'payment', None)
            if not payment:
                raise ValidationError('No hay comprobante por revisar.')
            if action == 'confirm':
                services.confirm_event_payment(payment, request.user)
            elif action == 'reject':
                services.reject_event_payment(payment, request.user, request.POST.get('reason', '')[:2000])
            else:
                raise ValidationError('Acción desconocida.')
            return redirect('events:purchase', code=code)
        except ValidationError as exc:
            error = error_text(exc)
        purchase.refresh_from_db()
    url = settings.PUBLIC_BASE_URL + reverse('event-public:portal', args=[purchase.secure_token])
    state_message = 'está confirmada' if purchase.status == 'CONFIRMED' else 'fue rechazada. Revisa el motivo y contacta al establecimiento'
    text = f'Tu compra para {purchase.event.name} {state_message}. Consulta y descarga tus entradas: {url}'
    phone = ''.join(c for c in purchase.customer_phone if c.isdigit())
    if len(phone) == 8:
        phone = '502' + phone
    return page(request, 'purchase_review.html', dict(purchase=purchase, error=error,
        whatsapp='https://wa.me/' + phone + '?' + urlencode({'text': text}),
        confirm_token=security.confirmation(request, 'confirm', code, purchase.updated_at.isoformat()),
        reject_token=security.confirmation(request, 'reject', code, purchase.updated_at.isoformat())))


@security.required
@require_GET
def proof(request, code):
    services.require(request.user, 'view_event_purchases')
    purchase = get_object_or_404(EventPurchase.objects.select_related('payment'), public_code=code)
    payment = getattr(purchase, 'payment', None)
    if not payment:
        raise Http404
    from PIL import Image
    try:
        file = payment.proof_image.open('rb')
        mime = Image.MIME[Image.open(file).format]
        file.seek(0)
        return private(FileResponse(file, content_type=mime))
    except (OSError, KeyError):
        raise Http404


@never_cache
@require_http_methods(['GET', 'POST'])
def public_event(request, slug):
    event = get_object_or_404(Event, slug=slug, status__in=queries.LIVE_STATUSES)
    return event_checkout(request, event)


def event_checkout(request, event, preview=False):
    error = ''
    if request.method == 'POST':
        if preview:
            raise PermissionDenied
        try:
            quantities = {}
            for key, value in request.POST.items():
                if key.startswith('qty_') and value:
                    if not value.isdigit() or not key[4:].isdigit():
                        raise ValidationError('Cantidad inválida.')
                    if int(value):
                        quantities[int(key[4:])] = int(value)
            table_id = request.POST.get('table', '')
            table = get_object_or_404(EventTableConfiguration, pk=table_id if table_id.isdigit() else None, event=event) if table_id else None
            purchase = services.create_purchase(event, request.POST.get('customer_name', ''), request.POST.get('customer_phone', ''), quantities, table)
            return redirect('event-public:portal', secure_token=purchase.secure_token)
        except ValidationError as exc:
            error = site.public_error(exc)
    now = timezone.now()
    sale_open = event.ticket_sales_enabled and event.ends_at > now
    types = [t for t in queries.ticket_type_rows(event) if t.is_active and not t.is_courtesy_type and t.price > 0
             and (preview or t.sale_starts_at <= now <= t.sale_ends_at)]
    for kind in types:
        kind.public_max = min(kind.max_per_purchase, kind.available)
    remaining = queries.get_event_capacity_summary(event)['remaining']
    tables = [t for t in queries.table_rows(event) if t.available and t.enabled and t.cover_per_person > 0
              and t.table.is_active and t.table.area.is_active and t.table.operational_status == 'ACTIVE'
              and t.ticket_type.is_active and t.capacity_snapshot <= remaining] if sale_open else []
    response = render(request, 'events/public.html', {
        **site.context(request, title=event.name, description=event.description[:155] or 'Entradas y mesas para '+event.name,
                       image=event.image.url if event.image else None, private=preview),
        'event':event, 'error':error, 'preview':preview, 'types':types, 'tables':tables,
        'guest_form':GuestForm(initial={'customer_name':request.POST.get('customer_name',''), 'customer_phone':request.POST.get('customer_phone','')}),
        'sale_open':sale_open})
    return private(response) if preview else response


@security.required
@require_GET
def preview(request, pk):
    services.require(request.user, 'view_events')
    return event_checkout(request, get_object_or_404(Event, pk=pk), preview=True)


@never_cache
@require_http_methods(['GET', 'POST'])
def portal(request, secure_token):
    purchase = get_object_or_404(EventPurchase.objects.select_related('event', 'payment'), secure_token=secure_token)
    form = PaymentForm(request.POST or None, request.FILES or None, initial={'amount': purchase.amount})
    error = ''
    if request.method == 'POST' and form.is_valid():
        try:
            services.submit_event_payment(purchase, **form.cleaned_data)
            return redirect('event-public:portal', secure_token=secure_token)
        except ValidationError as exc:
            error = error_text(exc)
    return private(render(request, 'events/portal.html', dict(**site.context(request, title='Tu compra', private=True), purchase=purchase, form=form, error=error, bank_details=transfer_bank(),
        tickets=purchase.tickets.select_related('ticket_type'))))


@never_cache
@require_GET
def ticket_page(request, qr_token):
    ticket = get_object_or_404(EventTicket.objects.select_related('event', 'ticket_type'), qr_token=qr_token)
    return private(render(request, 'events/ticket.html', {**site.context(request, title='Tu entrada', private=True), 'ticket': ticket}))


@never_cache
@require_GET
def qr_image(request, qr_token):
    ticket = get_object_or_404(EventTicket, qr_token=qr_token)
    from .documents import ticket_qr
    return private(HttpResponse(ticket_qr(ticket).getvalue(), content_type='image/png'))


@never_cache
@require_GET
def purchase_pdf(request, secure_token, number=None):
    purchase = get_object_or_404(EventPurchase, secure_token=secure_token)
    if purchase.status != 'CONFIRMED':
        raise Http404
    tickets = purchase.tickets.select_related('event', 'ticket_type', 'purchase').order_by('pk')
    if number:
        tickets = tickets.filter(ticket_number=number)
    if not tickets.exists():
        raise Http404
    from .documents import tickets_pdf
    return private(FileResponse(tickets_pdf(tickets), content_type='application/pdf', as_attachment=True, filename=(number or purchase.public_code)+'.pdf'))


@security.required
@require_GET
def courtesy_pdf(request, number):
    services.require(request.user, 'issue_courtesy_tickets')
    ticket = get_object_or_404(EventTicket.objects.select_related('event', 'ticket_type'), ticket_number=number, purchase__isnull=True)
    from .documents import tickets_pdf
    return private(FileResponse(tickets_pdf([ticket]), content_type='application/pdf', as_attachment=True, filename=number+'.pdf'))
