"""Catálogo explícito de permisos de negocio; Django sigue siendo la única matriz."""
from django.apps import apps
from django.contrib.auth.models import Permission
from django.db.models import Q

# Sólo los permisos especiales de estos modelos se publican. Nunca todos los permisos de un app.
MODULES = {
    'Operación': ('orders.TableOrder', 'payments.Payment'),
    'Caja': ('cash.CashSession', 'operations.CashAccessSession'),
    'Inventario': ('inventory.InventoryMovement', 'catalog.Product'),
    'Mesas': ('tables.VenueTable',),
    'Reservas': ('reservations.Reservation',),
    'Eventos': ('events.Event',),
    'Gerencia': ('cash.BusinessDay', 'core.BusinessSettings', 'audit.AuditLog'),
    'Impresión': ('printing.Printer', 'printing.PrintJob'),
    'Usuarios': ('accounts.User',),
}
EXTRA = {
    'Mesas': ['tables.view_venuetable', 'tables.add_venuetable', 'tables.change_venuetable'],
    'Operación': ['tables.view_venuetable', 'orders.view_tableorder', 'payments.view_payment'],
    'Caja': ['cash.view_cashmovement', 'cash.view_cashregister', 'cash.add_cashregister',
             'cash.change_cashregister', 'cash.configure_cash_register_device'],
    'Inventario': ['catalog.' + action + '_' + model for model in
        ('product', 'category', 'modifiergroup', 'modifieroption', 'combocomponent') for action in ('add', 'change')]
        + ['catalog.delete_combocomponent'],
    'Impresión': ['printing.view_printjob'],
    'Usuarios': ['accounts.view_user', 'accounts.add_user', 'accounts.change_user'],
}
LABELS = {
    'tables.add_venuetable': 'Crear mesas', 'tables.change_venuetable': 'Editar mesas y distribución',
    'accounts.view_user': 'Ver usuarios', 'accounts.add_user': 'Crear usuarios', 'accounts.change_user': 'Editar identidad de usuarios',
    'tables.view_venuetable': 'Consultar mesas', 'orders.view_tableorder': 'Consultar cuentas',
    'payments.view_payment': 'Consultar pagos', 'cash.view_cashmovement': 'Consultar movimientos de caja',
    'cash.view_cashregister': 'Ver cajas y computadoras', 'cash.add_cashregister': 'Crear cajas',
    'cash.change_cashregister': 'Editar y activar cajas',
    'cash.configure_cash_register_device': 'Configurar el navegador de una caja',
    'printing.view_printjob': 'Consultar impresiones', 'catalog.delete_combocomponent': 'Retirar componentes de combos',
}
for model, name in [('product', 'productos'), ('category', 'categorías'), ('modifiergroup', 'grupos de modificadores'),
                    ('modifieroption', 'opciones de modificadores'), ('combocomponent', 'componentes de combos')]:
    for action, label in [('add', 'Crear'), ('change', 'Editar')]:
        LABELS[f'catalog.{action}_{model}'] = f'{label} {name}'
GUARD = {'events.scan_event_ticket'}
PRESETS = {
    'MESERO': {'tables.view_venuetable', 'orders.view_tableorder', 'orders.open_table_order', 'orders.add_order_line',
               'orders.send_order', 'orders.manage_subaccounts', 'payments.record_payment', 'payments.close_order',
               'printing.print_customer_receipt'},
    'CAJERO': {'orders.view_tableorder', 'orders.create_quick_sale', 'orders.add_products_from_cash_register',
               'orders.add_order_line', 'orders.send_order',
               'cash.open_cash_session', 'cash.receive_waiter_cash', 'cash.close_cash_session', 'cash.view_cashmovement',
               'operations.request_cash_withdrawal', 'payments.record_payment', 'payments.close_order', 'printing.print_customer_receipt'},
    'GUARDIA': GUARD,
    'GERENTE': {'inventory.view_inventory', 'reservations.view_reservations', 'events.view_events',
                'accounts.view_user', 'cash.view_cash_session_financials', 'printing.view_printjob',
                'cash.view_cashregister', 'cash.add_cashregister', 'cash.change_cashregister',
                'cash.configure_cash_register_device', 'core.view_configuration',
                'core.view_reports',
                'accounts.add_user', 'accounts.change_user', 'accounts.change_user_role',
                'accounts.reset_user_pin', 'accounts.change_user_credentials',
                'accounts.activate_user', 'accounts.manage_user_permissions'},
}


def catalog():
    groups = {}
    for title, models in MODULES.items():
        entries = {}
        for label in models:
            model = apps.get_model(label)
            entries.update({model._meta.app_label + '.' + code: text.removeprefix('Puede ')[:1].upper() + text.removeprefix('Puede ')[1:]
                            for code, text in model._meta.permissions})
        entries.update({code: LABELS[code] for code in EXTRA.get(title, [])})
        groups[title] = entries
    return groups


def whitelist():
    return {code for group in catalog().values() for code in group}


def permission_map():
    query = Q(pk__in=[])
    for code in whitelist():
        app, codename = code.split('.')
        query |= Q(content_type__app_label=app, codename=codename)
    return {p.content_type.app_label + '.' + p.codename: p for p in Permission.objects.filter(query).select_related('content_type')}


def suggested(role):
    return {'core.view_reports'} if role == 'PROPIETARIO' else PRESETS.get(role, set())
