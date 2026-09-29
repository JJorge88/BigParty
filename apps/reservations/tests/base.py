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
from apps.reservations import services as s


def proof(format='PNG'):
    content = BytesIO()
    Image.new('RGB', (40, 40), 'white').save(content, format=format)
    return SimpleUploadedFile('proof.' + format.lower(), content.getvalue(), content_type='image/' + format.lower())


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReservationCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = get_user_model().objects.create_user(username='reservation-manager', password='Test-3b-992!', role='GERENTE', first_name='Julia')
        cls.manager.user_permissions.add(*Permission.objects.filter(content_type__app_label='reservations'))
        cls.waiter = get_user_model().objects.create_user(username='reservation-waiter', role='MESERO', first_name='Carlos')
        cls.admin = get_user_model().objects.create_superuser(username='reservation-admin', role='PROPIETARIO')
        cls.area = Area.objects.create(name='VIP', slug='vip')
        cls.table = VenueTable.objects.create(area=cls.area, name='VIP 2', capacity=6, reservable_web=True)

    def setUp(self):
        self.storage = TemporaryDirectory()
        setting = override_settings(RESERVATION_PROOF_ROOT=self.storage.name)
        setting.enable()
        self.addCleanup(setting.disable)
        self.addCleanup(self.storage.cleanup)
        self.start = timezone.localtime(timezone.now() + timedelta(days=1)).replace(second=0, microsecond=0)

    def request(self, table=None, start=None, **kwargs):
        start = start or self.start
        return s.create_public_reservation_request(table or self.table, 'Ana López', '+502 5555 5555',
            start.date(), start.time().replace(tzinfo=None), kwargs.get('party_size', 4))

    def approve(self, row=None, *, paid=False, application='CREDIT'):
        return s.approve_reservation(row or self.request(), self.manager, payment_required=paid,
            payment_value=300, payment_application=application)

    def confirmed(self, *, paid=False, application='CREDIT'):
        row = self.approve(paid=paid, application=application)
        if paid:
            payment = s.submit_reservation_payment(row, 300, 'REF-300', proof())
            row = s.confirm_reservation_payment(payment, self.manager)
        return row

    def revoke(self, permission):
        self.manager.user_permissions.remove(Permission.objects.get(codename=permission))
        for key in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
            self.manager.__dict__.pop(key, None)
