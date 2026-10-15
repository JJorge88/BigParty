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
    def test_invitation_aliases_keep_public_links(self):
        for spelling in ('inaguracion', 'ignaguracion'):
            for suffix, target in (('', '/inauguracion'), ('/', '/inauguracion'),
                                   ('/contador.js', '/inauguracion/contador.js')):
                with self.subTest(spelling=spelling, suffix=suffix):
                    self.assertRedirects(self.client.get('/' + spelling + suffix),
                                         target, status_code=301,
                                         fetch_redirect_response=False)

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



class PublicLayoutTests(EventCase):
    def test_event_geometry_levels_and_unavailable_tables(self):
        from apps.events import services
        self.table.level='LEVEL_2'
        self.table.layout_x=10; self.table.layout_y=20
        self.table.layout_width=25; self.table.layout_height=25
        self.table.layout_shape='CIRCLE'; self.table.save()
        url=f'/eventos/{self.event.slug}/'
        page=self.client.get(url)
        self.assertContains(page,'table-map-diagram')
        self.assertContains(page,'--x:10.0%;--y:20.0%;--w:25.0%;--h:25.0%')
        self.assertContains(page,'shape-circle')
        self.assertContains(page,'Nivel 2')
        self.assertEqual(len(page.context['table_groups']),1)
        other=VenueTable.objects.create(area=self.table.area,name='Planta baja',capacity=4,level='LEVEL_1',
            layout_x=10,layout_y=20,layout_width=25,layout_height=25)
        services.save_event_table(self.event,self.manager,other,self.vip,100)
        page=self.client.get(url)
        self.assertEqual(len(page.context['table_groups']),2)
        self.assertTrue(all(group['diagram'] for group in page.context['table_groups']))
        self.buy(table=True)
        page=self.client.get(url)
        self.assertContains(page,'No disponible')
        self.assertNotContains(page,f'name="table" value="{self.config.pk}"')

    def test_missing_geometry_uses_honest_list(self):
        page=self.client.get(f'/eventos/{self.event.slug}/')
        self.assertContains(page,'Ubicación en el plano pendiente de confirmar')
        self.assertContains(page,'table-map-grid')
        self.assertNotContains(page,'Nivel 2')


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
        self.assertRedirects(self.client.get('/reservas/'), '/eventos/')
        self.assertContains(home,'class="mobile-home"')
        self.assertContains(home,'aria-controls="public-nav"')
        self.assertContains(home,'images/invitation/big-party-logo-256.png', count=4)
        self.assertContains(home,'class="brand brand-logo"', count=1)
        self.assertContains(home,'class="brand brand-logo brand-logo--footer"', count=1)

    @override_settings(PUBLIC_INVITATION_ENABLED=True, PUBLIC_INVITATION_STARTS_AT='2026-10-22T14:00:00-06:00')
    def test_inauguration_has_official_logo_and_countdown(self):
        page = self.client.get('/inauguracion')
        self.assertContains(page, 'images/invitation/big-party-logo-256.png', count=3)
        self.assertContains(page, 'data-invitation-date="2026-10-22T14:00:00-06:00"')
        self.assertContains(page, 'data-countdown')
        for unit in ('data-days', 'data-hours', 'data-minutes', 'data-seconds'):
            self.assertContains(page, unit)
        self.assertContains(page, '2:00–5:00 p. m.')
        self.assertContains(page, '5:00 p. m.–1:00 a. m.')
        self.assertContains(page, 'Acto de inauguración')
        self.assertContains(page, 'Grupo Bembé, Imperio Efectivo y DJ Chama')
        self.assertContains(page, '>Entrada<')
        self.assertContains(page, '>Q60<')
        self.assertContains(page, 'A partir de las 6:00 p. m.')
        self.assertContains(page, '/inauguracion/contador.js?v=live-countdown-3')
        script = self.client.get('/inauguracion/contador.js')
        self.assertEqual(script['Content-Type'], 'text/javascript; charset=utf-8')
        self.assertContains(script, 'window.setInterval(update, 1000)')
        self.assertRedirects(self.client.get('/ignaguracion'), '/inauguracion', status_code=301, fetch_redirect_response=False)
