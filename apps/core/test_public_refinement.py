from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from django.test import SimpleTestCase, override_settings
from apps.core.templatetags.public_format import public_date, public_time, quetzales, payment_money
from apps.core.public_site import has_public_layout
from apps.venues.models import Area
from apps.tables.models import VenueTable
from apps.reservations.tests.base import ReservationCase
from apps.events.tests.base import EventCase


class PublicFormattingTests(SimpleTestCase):
    @override_settings(TIME_ZONE='America/Guatemala')
    def test_dates_use_local_day_and_24_hour_time(self):
        value = datetime(2026, 10, 5, 2, 5, tzinfo=dt_timezone.utc)
        self.assertEqual(public_date(value), 'Domingo 4 de octubre de 2026')
        self.assertEqual(public_time(value), '20:05')
        self.assertEqual(public_date(value.date()), 'Lunes 5 de octubre de 2026')
        self.assertEqual(public_time(value.time()), '02:05')
        self.assertEqual(public_date(None), '')

    def test_marketing_and_payment_precision_without_changing_values(self):
        for value, marketing, payment in [(Decimal('100'), 'Q100', 'Q100.00'),
            (Decimal('1234.5'), 'Q1,234.50', 'Q1,234.50'), (Decimal('99.995'), 'Q100', 'Q100.00'),
            (0, 'Q0', 'Q0.00')]:
            self.assertEqual(quetzales(value), marketing)
            self.assertEqual(payment_money(value), payment)
        for missing in (None, '', 'invalid', 'NaN', 'Infinity'):
            self.assertEqual(payment_money(missing), '')

    def test_layout_rejects_overlap_bounds_and_unconfigured_positions(self):
        row = dict(x=10, y=10, width=20, height=20)
        self.assertTrue(has_public_layout([row, dict(row, x=30)]))
        self.assertFalse(has_public_layout([row, dict(row, x=29)]))
        self.assertFalse(has_public_layout([dict(row, x=90)]))
        self.assertFalse(has_public_layout([dict(row, x=0, y=0)]))
        self.assertFalse(has_public_layout([]))



class PublicLayoutTests(ReservationCase):
    def test_configured_geometry_fallback_and_empty_area(self):
        self.table.layout_x=10; self.table.layout_y=20
        self.table.layout_width=25; self.table.layout_height=25
        self.table.layout_shape='CIRCLE'; self.table.save()
        Area.objects.create(name='Premium', slug='premium', sort_order=10)
        data={'date':self.start.date(), 'time':self.start.strftime('%H:%M'), 'party_size':4}
        page=self.client.get('/reservas/mesas/',data)
        self.assertContains(page,'table-map-diagram')
        self.assertContains(page,'--x:10.0%;--y:20.0%;--w:25.0%;--h:25.0%')
        self.assertContains(page,'shape-circle')
        self.assertContains(page,'--map-min:240px')
        self.assertContains(page,'Pronto podrás consultar mesas web en esta área.')
        self.assertNotContains(page,'table-map-grid')
        VenueTable.objects.create(area=self.area,name='Mesa superpuesta',capacity=4,reservable_web=True,
            layout_x=15,layout_y=25,layout_width=25,layout_height=25)
        page=self.client.get('/reservas/mesas/',data)
        self.assertContains(page,'table-map-grid')
        self.assertNotContains(page,'table-map-diagram')
        self.assertEqual(sum(len(g['tables']) for g in page.context['groups']),2)


class PublicComponentTests(EventCase):
    @override_settings(PUBLIC_LEVEL_IMAGES={}, PUBLIC_RESERVATION_IMAGE='', PUBLIC_EVENT_FALLBACK_IMAGE='')
    def test_independent_assets_and_single_event_composition(self):
        self.event.image='';self.event.save(update_fields=['image'])
        home=self.client.get('/')
        # Hero occurs once in visible markup; head preload/OG are intentionally retained.
        self.assertEqual(home.content.decode().split('<body',1)[1].count('nightlife-hero.webp'),1)
        for variant in ('sport','disco','premium','reservation','event'):
            self.assertContains(home,'atmosphere--'+variant)
        self.assertContains(self.client.get('/eventos/'),'event-grid--single')
        self.assertNotContains(self.client.get('/reservas/'), 'src="/static/images/public/nightlife-hero.webp"')
        self.assertContains(home,'class="mobile-home"')
        self.assertContains(home,'aria-controls="public-nav"')
