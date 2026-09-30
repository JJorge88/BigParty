from datetime import time
from decimal import Decimal
import json
import re
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase, Client, override_settings
from apps.accounts.models import User
from apps.audit.models import AuditLog
from apps.core.models import BusinessSettings, BusinessOpeningHours
from apps.core.configuration import business, save_configuration
from apps.operations.management.audit_views import visible_data


class VenueModelTests(TestCase):
    def test_defaults_and_optional_contact(self):
        obj = business()
        obj.full_clean()
        self.assertEqual(obj.latitude, Decimal('14.559363833208103'))
        self.assertEqual(obj.longitude, Decimal('-89.35266491165514'))
        self.assertEqual((obj.address_text, obj.public_phone, obj.minimum_entry_age), ('', '', 18))
        self.assertFalse(BusinessOpeningHours.objects.exists())

    def test_settings_validation(self):
        for field, value in [('latitude', 91), ('latitude', -91), ('longitude', 181), ('longitude', -181),
                             ('public_phone', 'javascript:alert(1)'), ('public_phone', '1234'), ('minimum_entry_age', 0)]:
            with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                BusinessSettings(**{field: value}).full_clean()
        BusinessSettings(latitude=-90, longitude=180).full_clean()

    def test_open_closed_and_overnight(self):
        for is_open, opens, closes in [(False, None, None), (True, time(10), time(20)), (True, time(20), time(4))]:
            row = BusinessOpeningHours(weekday=0, is_open=is_open, opens_at=opens, closes_at=closes)
            row.full_clean()
            self.assertEqual(row.crosses_midnight, is_open and closes < opens)

    def test_invalid_open_intervals_and_day(self):
        for values in [dict(opens_at=time(20), closes_at=time(20)), dict(opens_at=None, closes_at=time(4)),
                       dict(opens_at=time(20), closes_at=None), dict(weekday=7, opens_at=time(20), closes_at=time(4))]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                BusinessOpeningHours(**(dict(weekday=0, is_open=True) | values)).full_clean()

    def test_database_rejects_invalid_interval(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusinessOpeningHours.objects.create(weekday=0, is_open=True)

    def test_ordering_and_one_row_per_day(self):
        for day, order in [(0, 2), (6, 1), (5, 1)]:
            BusinessOpeningHours.objects.create(weekday=day, sort_order=order)
        self.assertEqual(list(BusinessOpeningHours.objects.values_list('weekday', flat=True)), [5, 6, 0])
        with self.assertRaises(IntegrityError), transaction.atomic():
            BusinessOpeningHours.objects.create(weekday=0)


class PublicVenueTests(TestCase):
    def structured(self, response):
        return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', response.content.decode(), re.S)[1])

    def test_empty_configuration_home_map_and_omissions(self):
        response = self.client.get('/')
        self.assertContains(response, '14.559363833208103')
        self.assertContains(response, '-89.35266491165514')
        self.assertContains(response, 'https://www.openstreetmap.org/export/embed.html?')
        self.assertContains(response, 'marker=14.559363833208103%2C-89.352664911655140')
        self.assertContains(response, 'destination=14.559363833208103%2C-89.352664911655140')
        self.assertContains(response, 'target="_blank" rel="noopener noreferrer"')
        self.assertEqual(response.content.decode().count('<details>'), 12)
        for forbidden in ['parqueo', 'parking', 'estacionamiento', 'WhatsApp', 'tel:', 'wa.me', 'venue-hours', 'Abierto ahora']:
            self.assertNotIn(forbidden, response.content.decode())
        data = self.structured(response)
        self.assertEqual(data['@type'], 'NightClub')
        self.assertEqual(Decimal(data['geo']['latitude']), business().latitude)
        for key in ('address', 'telephone', 'openingHoursSpecification'):
            self.assertNotIn(key, data)

    def test_configured_phone_address_and_dynamic_rules(self):
        BusinessSettings.objects.create(minimum_entry_age=21, address_text='Dirección de prueba', public_phone='+50255550123',
            identification_text='Identificación de prueba', dress_code='Vestimenta de prueba', admission_policy='Política de prueba')
        response = self.client.get('/')
        for value in ['Mayores de 21 años', 'Dirección de prueba', 'https://wa.me/50255550123', 'tel:+50255550123',
                      'Identificación de prueba', 'Vestimenta de prueba', 'Política de prueba']:
            self.assertContains(response, value)
        data = self.structured(response)
        self.assertEqual(data['telephone'], '+50255550123')
        self.assertEqual(data['address'], 'Dirección de prueba')
        BusinessSettings.objects.update(public_phone='', address_text='')
        response = self.client.get('/')
        self.assertNotContains(response, 'venue-contact')
        self.assertNotIn('telephone', self.structured(response))

    def test_schedule_and_faq_follow_published_days(self):
        row = BusinessOpeningHours.objects.create(weekday=5, is_open=True, opens_at=time(20), closes_at=time(4))
        BusinessOpeningHours.objects.create(weekday=0, is_open=False)
        response = self.client.get('/')
        self.assertContains(response, 'HORARIOS')
        self.assertContains(response, 'Sábado: 20:00 — 04:00 del día siguiente')
        self.assertContains(response, 'Cierre al día siguiente')
        spec = self.structured(response)['openingHoursSpecification']
        self.assertEqual(len(spec), 1)
        self.assertEqual(spec[0]['dayOfWeek'], 'https://schema.org/Saturday')
        self.assertEqual((spec[0]['opens'], spec[0]['closes']), ('20:00', '04:00'))
        row.is_open = False
        row.save()
        response = self.client.get('/')
        self.assertNotContains(response, 'venue-hours')
        self.assertNotIn('openingHoursSpecification', self.structured(response))

    def test_reservation_and_event_rules(self):
        response = self.client.get('/')
        for value in ['no equivale a una reserva confirmada', 'después de verificar el pago', 'enlace privado',
                      'no invalida automáticamente', 'QR único', '6 accesos individuales', 'capacidad completa',
                      'continúan siendo válidas', 'dejan de ser válidas', 'no es automática', '¿Qué es el cover?']:
            self.assertContains(response, value)

    def test_structured_data_and_public_text_escape_markup(self):
        attack = '</script><script>alert(1)</script>'
        BusinessSettings.objects.create(business_name=attack, admission_policy='<img src=x onerror=alert(1)>')
        response = self.client.get('/')
        self.assertNotContains(response, attack)
        self.assertNotContains(response, '<img src=x onerror=')
        self.assertEqual(self.structured(response)['name'], attack)

    @override_settings(SECURITY_HEADERS_ENABLED=True)
    def test_map_permission_only_on_home_and_no_geolocation(self):
        response = self.client.get('/')
        self.assertIn('frame-src https://www.openstreetmap.org', response['Content-Security-Policy'])
        self.assertIn('geolocation=()', response['Permissions-Policy'])
        self.assertNotIn('frame-src https://www.openstreetmap.org', self.client.get('/reservas/')['Content-Security-Policy'])


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class VenueManagementTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='venue_manager', password='test-venue-482!', role='GERENTE')
        self.manager.user_permissions.add(*Permission.objects.filter(content_type__app_label='core',
            codename__in=['view_configuration', 'change_business_configuration']))
        self.client.post('/gerencia/acceso/', {'username': self.manager.username, 'password': 'test-venue-482!'})

    def hours(self, **overrides):
        data = {'form-TOTAL_FORMS': 7, 'form-INITIAL_FORMS': 7, 'form-MIN_NUM_FORMS': 7, 'form-MAX_NUM_FORMS': 7}
        for day in range(7):
            data.update({f'form-{day}-is_open': 'False', f'form-{day}-opens_at': '', f'form-{day}-closes_at': '', f'form-{day}-sort_order': day})
        return data | overrides

    def test_separate_sections_and_read_does_not_publish(self):
        for path in ['negocio', 'business', 'location', 'hours', 'entry']:
            self.assertEqual(self.client.get(f'/gerencia/configuracion/{path}/').status_code, 200)
        self.assertFalse(BusinessOpeningHours.objects.exists())
        self.assertFalse(BusinessSettings.objects.exists())

    def test_location_post_audit_and_validation(self):
        data = dict(latitude='14.559363833208103', longitude='-89.35266491165514', address_text='', public_phone='')
        url = '/gerencia/configuracion/location/'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        log = AuditLog.objects.get(action='CONFIGURATION_UPDATED')
        self.assertEqual(log.user, self.manager)
        self.assertEqual(log.data['changes']['latitude']['after'], data['latitude'])
        self.assertTrue(any(label == 'Latitud' for label, value in visible_data(log.data)))
        self.assertContains(self.client.post(url, data | {'latitude': '91'}), '90')
        self.assertEqual(BusinessSettings.objects.get().latitude, Decimal(data['latitude']))
        self.assertEqual(AuditLog.objects.count(), 2)  # login plus configuration

    def test_entry_updates_home_and_audit(self):
        from apps.core.configuration import BUSINESS_FIELDS
        obj = business()
        data = {field: getattr(obj, field) for field in BUSINESS_FIELDS['entry']}
        data.update(minimum_entry_age=21, security_text='Seguridad de prueba', admission_policy='Política de prueba')
        self.assertEqual(self.client.post('/gerencia/configuracion/entry/', data).status_code, 302)
        self.assertContains(self.client.get('/'), 'Mayores de 21 años')
        log = AuditLog.objects.get(action='CONFIGURATION_UPDATED')
        self.assertEqual(log.data['changes']['minimum_entry_age']['after'], 21)

    def test_hours_post_midnight_audit_close_and_tampering(self):
        url = '/gerencia/configuracion/hours/'
        data = self.hours(**{'form-5-is_open': 'True', 'form-5-opens_at': '20:00', 'form-5-closes_at': '04:00', 'form-5-weekday': '0'})
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(BusinessOpeningHours.objects.get(weekday=5).crosses_midnight)
        self.assertEqual(BusinessOpeningHours.objects.filter(is_open=True).count(), 1)
        log = AuditLog.objects.get(action='CONFIGURATION_UPDATED')
        self.assertEqual(log.data['changes']['Sábado']['opens_at']['after'], '20:00:00')
        self.assertTrue(any('Sábado · Apertura' == label for label, value in visible_data(log.data)))
        self.assertContains(self.client.get('/'), 'Sábado: 20:00')
        self.assertEqual(self.client.post(url, self.hours()).status_code, 302)
        self.assertNotContains(self.client.get('/'), 'venue-hours')

    def test_invalid_hours_do_not_save_any_day(self):
        url = '/gerencia/configuracion/hours/'
        for data in [self.hours(**{'form-0-is_open': 'True'}),
                     self.hours(**{'form-5-is_open': 'True', 'form-5-opens_at': '20:00', 'form-5-closes_at': '20:00'}),
                     self.hours(**{'form-TOTAL_FORMS': 6}), self.hours(**{'form-TOTAL_FORMS': 8})]:
            self.assertEqual(self.client.post(url, data).status_code, 200)
            self.assertFalse(BusinessOpeningHours.objects.exists())
        self.assertFalse(AuditLog.objects.filter(action='CONFIGURATION_UPDATED').exists())

    def test_permissions_for_get_post_and_service(self):
        self.manager.user_permissions.remove(Permission.objects.get(content_type__app_label='core', codename='change_business_configuration'))
        for kind in ['location', 'entry', 'hours']:
            url = f'/gerencia/configuracion/{kind}/'
            self.assertEqual(self.client.get(url).status_code, 403)
            self.assertEqual(self.client.post(url, {}).status_code, 403)
        from django.core.exceptions import PermissionDenied
        with self.assertRaises(PermissionDenied):
            save_configuration(User.objects.get(pk=self.manager.pk), 'hours', [])
        self.assertFalse(BusinessOpeningHours.objects.exists())

    def test_csrf_rejects_missing_token_and_accepts_real_token(self):
        client = Client(enforce_csrf_checks=True)
        client.cookies = self.client.cookies.copy()
        for kind in ['location', 'entry', 'hours']:
            self.assertEqual(client.post(f'/gerencia/configuracion/{kind}/', {}).status_code, 403)
        url = '/gerencia/configuracion/hours/'
        page = client.get(url)
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode())[1]
        self.assertEqual(client.post(url, self.hours() | {'csrfmiddlewaretoken': token}).status_code, 302)
