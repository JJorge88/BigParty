"""Accesos de Gerencia derivados de permisos existentes, sin conceder accesos."""
from django.conf import settings
from django.urls import reverse
from django.views.decorators.http import require_GET
from . import security


def actions(user):
    specs = [
        ('Agregar un producto', 'Un trago, bebida o comida que vas a vender.', 'management:product-create', ('inventory.view_inventory','catalog.add_product'), 'local'),
        ('Recibí mercadería', 'Suma unidades de un producto que ya tienes registrado.', 'management:stock-create', ('inventory.view_inventory','inventory.receive_inventory'), 'local'),
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
