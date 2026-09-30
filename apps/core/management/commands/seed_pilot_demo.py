"""Opt-in, non-destructive fixtures for the dedicated development pilot database."""
from io import StringIO
from django.conf import settings
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction, IntegrityError
from django.utils.text import slugify
from apps.accounts.models import User, validate_pin
from apps.accounts.permissions import PRESETS, whitelist
from apps.audit.models import AuditLog
from apps.catalog.models import Category, Product, ModifierGroup, ModifierOption, ComboComponent, ProductAreaPrice
from apps.catalog.services import update_area_price
from apps.inventory.services import receive_stock
from apps.operations.models import OperationalDevice
from apps.tables.models import VenueTable
from apps.venues.models import Area, Zone

SEED = 'local-pilot-v1'
ACTION = 'pilot.demo.created'
USERS = (
    ('carlos_demo', 'Carlos', 'Demo', 'MESERO'),
    ('andrea_demo', 'Andrea', 'Demo', 'MESERO'),
    ('luis_caja_demo', 'Luis Caja', 'Demo', 'CAJERO'),
    ('gerente_demo', 'Gerente', 'Demo', 'GERENTE'),
    ('guardia_demo', 'Guardia', 'Demo', 'GUARDIA'),
)
PRODUCTS = (
    ('Gallo', 'cervezas', 25, 100, 'AREA_BAR'),
    ('Cabro', 'cervezas', 25, 80, 'AREA_BAR'),
    ('Corona', 'cervezas', 30, 80, 'AREA_BAR'),
    ('Whisky', 'licores', 45, 40, 'AREA_BAR'),
    ('Ron', 'licores', 40, 40, 'AREA_BAR'),
    ('Mojito', 'cocteles', 40, None, 'AREA_BAR'),
    ('Margarita', 'cocteles', 45, None, 'AREA_BAR'),
    ('Hamburguesa', 'comida', 65, 40, 'KITCHEN'),
    ('Papas fritas', 'comida', 30, 50, 'KITCHEN'),
    ('Nachos', 'snacks', 35, 50, 'KITCHEN'),
    ('Hielo', 'snacks', 0, 100, 'NONE'),
    ('Combo BIG', 'combos', 110, None, 'NONE'),
)
LAYOUT = {
    'discoteca': (
        ('Pista Central', [(f'Mesa {i:02}', 4) for i in range(1, 7)]),
        ('Barra / Periferia', [('Mesa 07', 4), ('Mesa 08', 4)]),
        ('Zona VIP', [('VIP 1', 6), ('VIP 2', 6)]),
    ),
    'sport-bar': (
        ('Salón', [('Sport 01', 4), ('Sport 02', 4), ('Sport 03', 4)]),
        ('Barra', [('Sport 04', 4), ('Sport VIP 1', 6)]),
    ),
    'premium': (
        ('Premium', [('Premium 01', 4), ('Premium 02', 4), ('Premium 03', 4)]),
        ('VIP', [('Premium VIP 1', 6)]),
    ),
}


def database_name():
    return connection.settings_dict['NAME']


class Command(BaseCommand):
    help = 'Crea datos demo sin resetear la operación, solo DEBUG/development/bigparty_pilot.'

    def add_arguments(self, parser):
        parser.add_argument('--pin', help='PIN elegido de 4–6 dígitos; nunca se imprime ni se inventa.')
        parser.add_argument('--manager-password', help='Contraseña elegida para gerente_demo; nunca se imprime.')

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('seed_pilot_demo requiere DEBUG=True.')
        if settings.DEPLOYMENT_MODE != 'development' or settings.SYNC_ENABLED:
            raise CommandError('El piloto requiere DEPLOYMENT_MODE=development y SYNC_ENABLED=false.')
        if database_name() != 'bigparty_pilot' or connection.vendor != 'postgresql':
            raise CommandError('El demo solo puede sembrarse en PostgreSQL bigparty_pilot.')
        if connection.settings_dict.get('HOST', '') not in ('', 'localhost', '127.0.0.1', '::1'):
            raise CommandError('El piloto requiere PostgreSQL local en loopback; no se contactará Cloud.')
        if settings.PRINTER_BACKEND != 'debug':
            raise CommandError('El piloto requiere PRINTER_BACKEND=debug; no se enviarán impresiones reales.')
        from apps.core.ops.recovery import status
        if status()['active']:
            raise CommandError('RECOVERY_MODE: no se siembran datos durante recuperación.')
        pin, password = options['pin'], options['manager_password']
        try:
            if pin is not None:
                validate_pin(pin)
                if len(pin) > 6:
                    raise ValidationError('Los accesos operativos existentes requieren PIN de 4–6 dígitos.')
            if password is not None:
                validate_password(password, User(username='gerente_demo', first_name='Gerente', last_name='Demo'))
            self.seed(pin, password)
        except ValidationError as exc:
            raise CommandError('Datos demo rechazados: ' + ' '.join(exc.messages)) from None
        except IntegrityError:
            raise CommandError('Conflicto de datos demo; no se guardaron cambios. Revisa registros existentes.') from None
        self.stdout.write(self.style.SUCCESS('Demo listo: 3 áreas, 7 zonas, 19 mesas, 12 productos, 5 usuarios y 1 tablet.'))
        self.stdout.write('Datos existentes conservados. No se abrió jornada ni se crearon órdenes, reservas o entradas.')
        if pin is None:
            self.stdout.write('PIN no proporcionado: se conservaron los existentes; los usuarios nuevos no pueden entrar con PIN. Repite con --pin elegido.')
        if password is None:
            self.stdout.write('Contraseña no proporcionada: se conserva la existente; gerente nuevo sin acceso por contraseña. Repite con --manager-password elegida.')

    def owned(self, model, key, lookup, defaults=None):
        """Existing audit records identify ownership even after a demo object is renamed."""
        mark = AuditLog.objects.filter(action=ACTION, entity=model._meta.label_lower,
            data__seed=SEED, data__key=key).first()
        if mark:
            obj = model.objects.filter(pk=mark.entity_id).first()
            if obj is None:
                raise CommandError(f'El registro demo {key} fue eliminado. No se reconstruye ni se resetea automáticamente.')
            return obj, False
        if model.objects.filter(**lookup).exists():
            raise CommandError(f'Conflicto con registro ajeno al demo: {key}. No se modificó.')
        obj = model.objects.create(**lookup, **(defaults or {}))
        AuditLog.objects.create(action=ACTION, entity=model._meta.label_lower,
            entity_id=str(obj.pk), data={'seed': SEED, 'key': key})
        return obj, True

    def permissions(self, user, role):
        codes = (whitelist() | {'operations.configure_operational_device', 'cash.configure_cash_register_device'}
                 if role == 'GERENTE' else PRESETS[role])
        if role == 'CAJERO':
            codes = codes | {'orders.add_order_line', 'orders.send_order'}
        permissions = []
        for code in sorted(codes):
            app, name = code.split('.')
            try:
                permissions.append(Permission.objects.get(content_type__app_label=app, codename=name))
            except Permission.DoesNotExist:
                raise CommandError(f'Falta el permiso {code}; ejecuta migrate.') from None
        user.user_permissions.add(*permissions)

    @transaction.atomic
    def seed(self, pin, password):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [42810501])
        for command in ('seed_bigparty_defaults', 'seed_catalog_defaults', 'seed_cash_defaults', 'seed_printer_defaults'):
            call_command(command, stdout=StringIO())
        users = {}
        for username, first, last, role in USERS:
            user, created = self.owned(User, username, {'username': username},
                {'first_name': first, 'last_name': last, 'role': role, 'is_active': True,
                 'is_staff': role == 'GERENTE', 'is_superuser': False})
            if created:
                user.set_unusable_password()
            if user.role == role:
                self.permissions(user, role)
            changed = created
            if pin is not None and not user.check_pin(pin):
                user.set_pin(pin)
                changed = True
            if username == 'gerente_demo' and password is not None and not user.check_password(password):
                user.set_password(password)
                changed = True
            if changed:
                user.save()
            users[username] = user
        manager = users['gerente_demo']
        areas = {area.slug: area for area in Area.objects.filter(slug__in=LAYOUT)}
        for slug, groups in LAYOUT.items():
            area = areas[slug]
            for group_index, (name, tables) in enumerate(groups):
                zone, _ = self.owned(Zone, slug + '/' + name,
                    {'area': area, 'slug': 'pilot-' + slugify(name)},
                    {'name': name, 'sort_order': (group_index + 1) * 10})
                for index, (table_name, capacity) in enumerate(tables):
                    self.owned(VenueTable, slug + '/' + table_name, {'area': area, 'name': table_name},
                        {'zone': zone, 'capacity': capacity, 'reservable_web': True,
                         'sort_order': (index + 1) * 10, 'layout_x': 5 + (index % 2) * 50,
                         'layout_y': 3 + (index // 2) * 32, 'layout_width': 40, 'layout_height': 27})
        products = {}
        for name, category, price, stock, route in PRODUCTS:
            product, created = self.owned(Product, name, {'slug': 'pilot-' + slugify(name)},
                {'name': name, 'category': Category.objects.get(slug=category), 'base_price': price,
                 'track_inventory': stock is not None, 'stock_quantity': 0,
                 'visible_in_pos': name != 'Hielo', 'preparation_route': route, 'is_combo': name == 'Combo BIG'})
            products[name] = product
            if created and stock:
                receive_stock(product, stock, user=manager, reason='Carga inicial del piloto local DEMO')
        for name, price in [('Gallo', 30), ('Corona', 35), ('Whisky', 50)]:
            product = products[name]
            # Price services preserve history. Once created, manual pilot changes remain untouched.
            key = 'premium/' + name
            if not AuditLog.objects.filter(action=ACTION, entity='catalog.productareaprice', data__seed=SEED, data__key=key).exists():
                if ProductAreaPrice.objects.filter(product=product, area=areas['premium']).exists():
                    raise CommandError('Precio Premium existente ajeno al demo; no se modificó.')
                price_row = update_area_price(product, areas['premium'], price, user=manager)
                AuditLog.objects.create(action=ACTION, entity='catalog.productareaprice', entity_id=str(price_row.pk), data={'seed': SEED, 'key': key})
        groups = [
            ('Hamburguesa', 'Preparación', 'SINGLE', [('Normal', 0), ('Sin cebolla', 0), ('Sin tomate', 0)]),
            ('Hamburguesa', 'Extras', 'MULTIPLE', [('Extra queso', 10), ('Extra tocino', 15)]),
            ('Whisky', 'Preparación', 'SINGLE', [('Solo', 0), ('Con hielo', 0), ('Con soda', 0)]),
            ('Whisky', 'Extras', 'MULTIPLE', [('Energética', 15)]),
        ]
        for product_name, name, selection, options in groups:
            key = product_name + '/' + name
            group, _ = self.owned(ModifierGroup, key, {'product': products[product_name], 'name': name},
                {'selection_type': selection, 'max_selections': 1 if selection == 'SINGLE' else len(options),
                 'sort_order': 10 if name == 'Preparación' else 20})
            for index, (option_name, delta) in enumerate(options):
                self.owned(ModifierOption, key + '/' + option_name, {'group': group, 'name': option_name},
                    {'price_delta': delta, 'sort_order': index * 10})
        for index, name in enumerate(('Hamburguesa', 'Papas fritas', 'Gallo')):
            self.owned(ComboComponent, 'Combo BIG/' + name,
                {'combo': products['Combo BIG'], 'component': products[name]}, {'quantity': 1, 'sort_order': index * 10})
        self.owned(OperationalDevice, 'TAB-DISCO-DEMO', {'code': 'TAB-DISCO-DEMO'},
            {'name': 'Tablet Discoteca Demo', 'area': areas['discoteca'], 'device_type': 'WAITER_TABLET'})
