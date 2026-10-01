"""Accesos de Gerencia derivados de permisos existentes, sin conceder accesos."""
from django.conf import settings
from django.urls import reverse
from django.views.decorators.http import require_GET
from . import security


def actions(user):
    specs = [
        ('Producto', 'Agrega un trago, bebida o comida con su precio y existencias iniciales.', 'management:product-create', ('inventory.view_inventory','catalog.add_product'), 'local'),
        ('Entrada de inventario', 'Selecciona un producto y registra la cantidad recibida.', 'management:stock-create', ('inventory.view_inventory','inventory.receive_inventory'), 'local'),
        ('Mesa', 'Elige el área y coloca la nueva mesa en el plano.', 'management:table-start', ('tables.view_venuetable','tables.add_venuetable'), 'local'),
        ('Reserva', 'Ingresa el cliente, la mesa y la fecha en un solo formulario.', 'reservations:create', ('reservations.create_reservation',), 'cloud'),
        ('Evento', 'Prepara la información, las entradas y el aforo paso a paso.', 'events:create', ('events.create_event',), 'cloud'),
        ('Usuario', 'Crea su acceso y luego revisa sus permisos de trabajo.', 'management:user-create', ('accounts.view_user','accounts.add_user'), 'local'),
        ('Categoría', 'Organiza los productos: cervezas, cócteles, comida y más.', 'management:category-create', ('inventory.view_inventory','catalog.add_category'), 'local'),
    ]
    own = 'cloud' if settings.DEPLOYMENT_MODE == 'cloud' else 'local'
    return [dict(title=title, description=description, url=reverse(route)) for title,description,route,perms,authority in specs
            if all(user.has_perm(p) for p in perms) and (not settings.SYNC_ENABLED or authority == own)]


@require_GET
@security.required
def hub(request):
    from .views import page
    return page(request, 'add', {'add_actions': actions(request.user)}, section='agregar')
