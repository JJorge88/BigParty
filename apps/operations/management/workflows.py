"""Accesos de Gerencia derivados de permisos existentes, sin conceder accesos."""
from django.conf import settings
from django.urls import reverse
from django.views.decorators.http import require_GET
from . import security


def actions(user):
    specs = [
        ('Agregar un producto', 'Un trago, bebida o comida que vas a vender.', 'management:product-create', ('inventory.view_inventory','catalog.add_product'), 'local'),
        ('Recibí mercadería', 'Suma unidades de un producto que ya tienes registrado.', 'management:inventory-receive', ('inventory.view_inventory','inventory.receive_inventory'), 'local'),
        ('Agregar una mesa', 'Elige dónde va y cuántas personas caben.', 'management:table-start', ('tables.view_venuetable','tables.add_venuetable'), 'local'),
        ('Anotar una reserva', 'Guarda una mesa para un cliente.', 'reservations:create', ('reservations.create_reservation',), 'cloud'),
        ('Crear un evento', 'Agrega la fecha, las entradas y la capacidad.', 'events:create', ('events.create_event',), 'cloud'),
        ('Agregar un empleado', 'Crea su usuario y elige qué puede hacer.', 'management:user-create', ('accounts.view_user','accounts.add_user'), 'local'),
        ('Crear una categoría', 'Agrupa tus productos, por ejemplo: cervezas o comida.', 'management:category-create', ('inventory.view_inventory','catalog.add_category'), 'local'),
    ]
    own = 'cloud' if settings.DEPLOYMENT_MODE == 'cloud' else 'local'
    return [dict(title=title, description=description, url=reverse(route)) for title,description,route,perms,authority in specs
            if all(user.has_perm(p) for p in perms) and (not settings.SYNC_ENABLED or authority == own)]


@require_GET
@security.required
def hub(request):
    from .views import page
    return page(request, 'add', {'add_actions': actions(request.user)}, section='agregar')


def pending_tasks(user, dashboard):
    from django.db.models import F, Q
    from django.utils import timezone
    from apps.catalog.models import Product
    from apps.reservations.models import Reservation
    result = []
    if user.has_perm('core.view_configuration'):
        from apps.core.ops.backups import health
        backup = health()
        if not backup['ok']:
            result.append({'title': 'Respaldo por revisar', 'detail': backup['message'], 'url': reverse('backup-status'), 'action': 'Revisar respaldo'})
    if user.has_perm('inventory.view_inventory'):
        tracked = Product.objects.filter(is_active=True, track_inventory=True)
        for count, title, singular, state in (
            (tracked.filter(stock_quantity=0).count(), 'productos agotados', 'producto agotado', 'out'),
            (tracked.filter(stock_quantity__gt=0, stock_quantity__lte=F('minimum_stock')).count(), 'productos con pocas unidades', 'producto con pocas unidades', 'low'),
        ):
            if count:
                result.append({'title': f'{count} {singular if count == 1 else title}', 'detail': 'Revisa si necesitas recibir más mercadería.',
                    'url': reverse('management:inventory') + '?state=' + state, 'action': 'Ver productos'})
    if user.has_perm('reservations.view_reservations'):
        live = Reservation.objects.exclude(Q(status='PENDING_REVIEW', hold_expires_at__lte=timezone.now()))
        for state, label, singular in [('PENDING_REVIEW', 'reservas por revisar', 'reserva por revisar'), ('PAYMENT_REVIEW', 'pagos de reserva por verificar', 'pago de reserva por verificar')]:
            count = live.filter(status=state).count()
            if count:
                result.append({'title': f'{count} {singular if count == 1 else label}', 'detail': 'Abre la lista para revisar cada solicitud.',
                    'url': reverse('reservations:list') + '?filter=' + state, 'action': 'Revisar reservas'})
    for item in dashboard.get('attention', []):
        if item.get('url'):
            result.append({**item, 'action': 'Revisar'})
    if dashboard.get('blockers'):
        count = len(dashboard['blockers'])
        result.append({'title': f'{count} pendientes antes de cerrar el día',
            'detail': 'Revisa las cuentas y cajas que siguen abiertas.',
            'url': reverse('management:closures'), 'action': 'Ver pendientes de cierre'})
    return result
