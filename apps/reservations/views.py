from apps.core.configuration import bank as transfer_bank
from apps.core import public_site as site
from django.contrib.auth import get_user_model
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_GET

from apps.operations.management import security
from apps.operations.management.queries import base
from . import services
from .forms import PaymentTermsForm, ManualReservationForm, SettingsForm, SubmitPaymentForm
from .messages import whatsapp_url, client_url
from .models import Reservation
from .queries import get_settings
from .credits import credit_summary


def terms_initial():
    config = get_settings()
    return {'payment_required': config.advance_payment_enabled, 'payment_type': config.advance_payment_type,
            'payment_value': config.advance_payment_value, 'payment_application': config.advance_payment_application,
            'payment_base_amount': 0, 'duration': config.default_duration_minutes}


def page(request, template, context, status=200):
    return render(request, 'reservations/' + template, {**base(request, 'reservas'), **context}, status=status)


@security.required
@require_GET
def index(request):
    services.require(request.user, 'view_reservations')
    now = timezone.now()
    # GET es de lectura: estado efectivo sin escribir; comandos conservan auditoría de expiración.
    rows = Reservation.objects.select_related('table', 'area')
    live = rows.exclude(Q(status='PENDING_REVIEW', hold_expires_at__lte=now) | Q(status='AWAITING_PAYMENT', payment_expires_at__lte=now))
    counts = {'pending': live.filter(status='PENDING_REVIEW').count(), 'payment': live.filter(status='AWAITING_PAYMENT').count(),
              'today': live.filter(status='CONFIRMED', reservation_date=timezone.localdate()).count(),
              'upcoming': live.filter(status='CONFIRMED', starts_at__gte=now).count()}
    selected = request.GET.get('filter', '')
    filters = [('', 'Todas'), ('PENDING_REVIEW', 'Pendientes'), ('AWAITING_PAYMENT', 'Esperando pago'),
               ('PAYMENT_REVIEW', 'Por verificar'), ('CONFIRMED', 'Confirmadas'), ('today', 'Hoy')]
    if selected == 'today':
        rows = rows.filter(reservation_date=timezone.localdate())
    elif selected in dict(filters) and selected:
        rows = live.filter(status=selected)
    search = request.GET.get('q', '').strip()[:120]
    if search:
        rows = rows.filter(Q(customer_name__icontains=search) | Q(customer_phone__icontains=search) |
                           Q(public_code__icontains=search) | Q(table__name__icontains=search))
    from django.core.paginator import Paginator
    paginated = Paginator(rows.order_by('-starts_at', '-pk'), 30).get_page(request.GET.get('page'))
    for row in paginated:
        row.effective_expired = bool(row.deadline and row.deadline <= now)
    return page(request, 'list.html', {'rows': paginated, 'counts': counts, 'filters': filters, 'selected': selected, 'search': search})


@security.required
@require_http_methods(['GET', 'POST'])
def create(request):
    services.require(request.user, 'create_reservation')
    form = ManualReservationForm(request.POST or None, initial=terms_initial())
    error = ''
    if request.method == 'POST' and form.is_valid():
        try:
            row = services.create_manual_reservation(user=request.user, **form.cleaned_data)
            messages.success(request, 'Reserva creada. Revisa sus datos y el siguiente paso de pago, si corresponde.')
            return redirect('reservations:detail', code=row.public_code)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
    return page(request, 'form.html', {'form': form, 'error': error, 'title': 'Crear reserva', 'subtitle': 'Reserva interna · confirmación directa', 'button': 'Crear reserva', 'manual': True,
        'groups': [(title, [form[key] for key in keys]) for title,keys in (('1. Fecha y grupo', ('date','time','duration','party_size')),('2. Mesa disponible', ('table',)),('3. Cliente', ('customer_name','customer_phone')),('4. Anticipo', ('payment_required','payment_type','payment_value','payment_application','payment_base_amount')))]})


@security.required
@require_http_methods(['GET', 'POST'])
def configure(request):
    services.require(request.user, 'configure_reservations')
    form = SettingsForm(request.POST or None, instance=get_settings())
    error, saved = '', False
    if request.method == 'POST' and form.is_valid():
        try:
            services.configure_reservations(request.user, **form.cleaned_data)
            saved = True
        except ValidationError as exc:
            error = ' '.join(exc.messages)
    return page(request, 'form.html', {'form': form, 'error': error, 'saved': saved, 'title': 'Configuración de reservas',
                                      'subtitle': 'Valores iniciales para nuevas reservas', 'button': 'Guardar configuración'})


ACTIONS = {'approve': 'approve_reservation', 'reject': 'reject_reservation', 'verify': 'verify_reservation_payment',
           'reject-payment': 'reject_reservation_payment', 'arrive': 'confirm_reservation_arrival',
           'cancel': 'cancel_reservation', 'no-show': 'mark_reservation_no_show'}


def _action(request, row, form):
    action = request.POST.get('action')
    if action not in ACTIONS:
        raise ValidationError('Acción desconocida.')
    services.require(request.user, ACTIONS[action])
    with transaction.atomic():
        row = services.locked(row)
        security.verify_confirmation(request, action, row.public_code, row.updated_at.isoformat())
        reason = request.POST.get('reason', '')[:2000]
        if action == 'approve':
            if not form.is_valid():
                raise ValidationError('Revisa los datos del anticipo.')
            services.approve_reservation(row, request.user, **form.cleaned_data)
        elif action == 'reject':
            services.reject_reservation(row, request.user, reason)
        elif action == 'verify':
            services.confirm_reservation_payment(row.payment, request.user)
        elif action == 'reject-payment':
            services.reject_reservation_payment(row.payment, request.user, reason)
        elif action == 'arrive':
            waiter = get_user_model().objects.filter(pk=request.POST.get('waiter') if request.POST.get('waiter', '').isdigit() else None).first()
            services.confirm_reservation_arrival(row, request.user, waiter)
        elif action == 'cancel':
            services.cancel_reservation(row, request.user, reason)
        else:
            services.mark_reservation_no_show(row, request.user, reason)


@security.required
@require_http_methods(['GET', 'POST'])
def detail(request, code):
    services.require(request.user, 'view_reservations')
    row = get_object_or_404(Reservation.objects.select_related('table', 'area', 'payment', 'order'), public_code=code)
    form = PaymentTermsForm(request.POST if request.method == 'POST' and request.POST.get('action') == 'approve' else None, initial=terms_initial())
    error = ''
    if request.method == 'POST':
        try:
            _action(request, row, form)
            return redirect('reservations:detail', code=code)
        except (ValidationError, Reservation.payment.RelatedObjectDoesNotExist) as exc:
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'No hay un pago pendiente para esta reserva.'
        row.refresh_from_db()
    expired = row.status == 'EXPIRED' or bool(row.deadline and row.deadline <= timezone.now())
    actions = {action.replace('-', '_') + '_token': security.confirmation(request, action, code, row.updated_at.isoformat()) for action in ACTIONS}
    allowed = {'can_' + action.replace('-', '_'): request.user.has_perm('reservations.' + permission) for action, permission in ACTIONS.items()}
    from django.conf import settings
    if settings.SYNC_ENABLED:
        if settings.DEPLOYMENT_MODE=='local_node':allowed={key:value if key=='can_arrive' else False for key,value in allowed.items()}
        elif settings.DEPLOYMENT_MODE=='cloud':allowed['can_arrive']=False
    return page(request, 'detail.html', {'bank_details': transfer_bank(), 'reservation': row, 'form': form, 'error': error, 'expired': expired,
        'waiters': get_user_model().objects.filter(is_active=True, role='MESERO').order_by('first_name', 'username'),
        'whatsapp': whatsapp_url(row), 'client_url': client_url(row), 'credit': credit_summary(row.order) if row.order_id else None,
        **actions, **allowed}, status=409 if error else 200)


@never_cache
@require_http_methods(['GET', 'POST'])
def client_detail(request, secure_token):
    row = get_object_or_404(Reservation.objects.select_related('table'), secure_token=secure_token)
    expired = row.status == 'EXPIRED' or bool(row.deadline and row.deadline <= timezone.now())
    form = SubmitPaymentForm(request.POST or None, request.FILES or None, initial={'amount': row.payment_amount})
    form.fields['proof_image'].required = not row.created_by_id
    error = ''
    if request.method == 'POST' and form.is_valid():
        try:
            services.submit_reservation_payment(row, **form.cleaned_data)
            return redirect('reservation-client:detail', secure_token=secure_token)
        except ValidationError as exc:
            error = ' '.join(exc.messages)
        row.refresh_from_db()
    response = render(request, 'reservations/client.html', {**site.context(request, title='Tu reserva', private=True), 'bank_details': transfer_bank(), 'reservation': row, 'form': form, 'expired': expired, 'error': error})
    response['Referrer-Policy'] = 'same-origin'
    response['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@security.required
@require_GET
def proof(request, code):
    services.require(request.user, 'view_reservations')
    row = get_object_or_404(Reservation.objects.select_related('payment'), public_code=code)
    try:
        image = row.payment.proof_image
    except Reservation.payment.RelatedObjectDoesNotExist:
        raise Http404
    if not image:
        raise Http404
    try:
        response = FileResponse(image.open('rb'), content_type='application/octet-stream', as_attachment=True, filename='comprobante-' + row.public_code + '.image')
        # Inline visualización solo de imágenes previamente verificadas, sin confiar en extensión.
        from PIL import Image
        opened = Image.open(image)
        response['Content-Type'] = Image.MIME[opened.format]
        image.seek(0)
        response['Content-Disposition'] = 'inline'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Cache-Control'] = 'no-store, private'
        return response
    except (FileNotFoundError, OSError):
        raise Http404


@security.required
@require_GET
def availability(request):
    from datetime import date, time
    from .queries import get_available_tables
    services.require(request.user, 'create_reservation')
    try:
        selected_date = date.fromisoformat(request.GET.get('date', ''))
        selected_time = time.fromisoformat(request.GET.get('time', ''))
        duration = int(request.GET.get('duration', '180'))
        party = int(request.GET.get('party_size', '0'))
        if not 1 <= duration <= 1440 or party < 1: raise ValueError()
        rows = get_available_tables(selected_date, selected_time, duration, party, public=False).select_related('area')
        return JsonResponse({'tables': [{'id': row.pk, 'label': f'{row.area.name} · {row.name} — {row.capacity} personas'} for row in rows]})
    except (ValueError, ValidationError):
        return JsonResponse({'error': 'Revisa fecha, hora, duración y personas.'}, status=400)
