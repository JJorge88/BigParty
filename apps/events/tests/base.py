from datetime import timedelta
from io import BytesIO
from tempfile import TemporaryDirectory
from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.events import services as s


def picture(name='proof.png'):
    output = BytesIO()
    Image.new('RGB', (80, 80), '#d5bd95').save(output, 'PNG')
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')


class Fixtures:
    def setUp(self):
        super().setUp()
        self.storage = TemporaryDirectory(prefix='bigparty-events-tests-')
        self.addCleanup(self.storage.cleanup)
        override = override_settings(MEDIA_ROOT=self.storage.name+'/media', EVENT_PROOF_ROOT=self.storage.name+'/proof',
            PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
        override.enable(); self.addCleanup(override.disable)
        User = get_user_model()
        self.manager = User.objects.create_user(username='event-manager', password='Event-Test-32!', role='GERENTE')
        self.manager.user_permissions.set(Permission.objects.filter(content_type__app_label='events'))
        self.guard = User.objects.create_user(username='event-guard', role='GUARDIA')
        self.guard.set_pin('123456'); self.guard.save()
        self.guard.user_permissions.add(Permission.objects.get(codename='scan_event_ticket', content_type__app_label='events'))
        self.start = timezone.now()+timedelta(days=2)
        self.event = s.create_event(self.manager, name='Noche Especial', starts_at=self.start, ends_at=self.start+timedelta(hours=6), image=picture('banner.png'), maximum_capacity=100)
        self.general = self.kind('General', 100, 50)
        self.vip = self.kind('VIP', 150, 30)
        self.courtesy = self.kind('Cortesía', 0, 10, is_courtesy_type=True)
        area = Area.objects.create(name='Event VIP', slug='event-vip')
        self.table = VenueTable.objects.create(area=area, name='VIP 2', capacity=6)
        self.config = s.save_event_table(self.event, self.manager, self.table, self.vip, 100)
        self.event = s.publish_event(self.event, self.manager)

    def kind(self, name, price, capacity, **data):
        return s.save_ticket_type(self.event, self.manager, name=name, price=price, capacity=capacity,
            sale_starts_at=timezone.now()-timedelta(days=1), sale_ends_at=self.start, max_per_purchase=10, **data)

    def buy(self, quantities=None, table=False):
        return s.create_purchase(self.event, 'Ana Compradora', '+50255555555',
            quantities if quantities is not None else (None if table else {self.general.pk: 2}), self.config if table else None)

    def submit(self, purchase=None):
        purchase = purchase or self.buy()
        return s.submit_event_payment(purchase, purchase.amount, 'TRANSFER-123', picture())

    def confirm(self, purchase=None):
        return s.confirm_event_payment(self.submit(purchase), self.manager)

    def revoke(self, permission):
        self.manager.user_permissions.remove(Permission.objects.get(codename=permission, content_type__app_label='events'))
        for name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.manager.__dict__.pop(name, None)


class EventCase(Fixtures, TestCase):
    pass
