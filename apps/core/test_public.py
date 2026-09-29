from datetime import timedelta
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.events.tests.base import EventCase
from apps.events.models import Event, EventPurchase
from apps.reservations.tests.base import ReservationCase, proof
from apps.reservations.models import Reservation, ReservationSettings
from apps.reservations import services as reservations
from apps.tables.models import VenueTable


@override_settings(PUBLIC_BASE_URL='https://example.test')
class PublicEventTests(EventCase):
    def url(self):
        return reverse('event-public:event', args=[self.event.slug])

    def test_home_featured_only_published_and_public_index_filter(self):
        draft=Event.objects.create(name='Secreto borrador',slug='secret',created_by=self.manager,starts_at=self.start,ends_at=self.start+timedelta(hours=4))
        self.assertContains(self.client.get('/'),self.event.name)
        for path in ['/', '/eventos/', '/sitemap.xml']:
            response=self.client.get(path)
            self.assertNotContains(response,draft.name)
            self.assertNotContains(response,'/secret/')
        Event.objects.filter(pk=self.event.pk).update(status='RESCHEDULED')
        self.assertNotContains(self.client.get('/'),self.event.name)
        self.assertContains(self.client.get('/eventos/'),self.event.name)
        self.assertContains(self.client.get(self.url()),'Evento reprogramado')

    def test_seo_canonical_og_and_no_private_urls_in_sitemap(self):
        page=self.client.get(self.url())
        self.assertNotIn('X-Robots-Tag',page)
        self.assertContains(page,'https://example.test'+self.url())
        self.assertContains(page,'https://example.test'+self.event.image.url)
        self.assertNotContains(page,'noindex')
        purchase=self.buy()
        sitemap=self.client.get('/sitemap.xml')
        self.assertContains(sitemap,'https://example.test/reservas/')
        for secret in [purchase.secure_token,'/gerencia/','/compra/','/entrada/','/mesas/']:
            self.assertNotContains(sitemap,secret)
        robots=self.client.get('/robots.txt')
        self.assertContains(robots,'Disallow: /eventos/compra/')
        self.assertContains(robots,'Sitemap: https://example.test/sitemap.xml')

    def test_sold_out_visible_courtesy_and_inactive_hidden(self):
        self.general.capacity=0; self.general.save(update_fields=['capacity'])
        self.vip.is_active=False;self.vip.save(update_fields=['is_active'])
        page=self.client.get(self.url())
        self.assertContains(page,'General');self.assertContains(page,'Agotado')
        self.assertNotContains(page,'Cortesía');self.assertNotContains(page,'name="qty_'+str(self.vip.pk)+'"')

    def test_maximum_and_mixed_purchase_backend(self):
        payload={'customer_name':'Ana','customer_phone':'55555555',f'qty_{self.general.pk}':'11'}
        self.assertContains(self.client.post(self.url(),payload),'Cantidad fuera del límite permitido.')
        self.assertFalse(EventPurchase.objects.exists())
        payload.update({f'qty_{self.general.pk}':'2',f'qty_{self.vip.pk}':'1'})
        response=self.client.post(self.url(),payload)
        self.assertEqual(response.status_code,302)
        self.assertEqual(EventPurchase.objects.get().amount,350)

    def test_event_table_price_hold_and_hidden_after_sale(self):
        page=self.client.get(self.url())
        self.assertContains(page,'Q600.00')
        self.assertContains(page,'6 entradas individuales con QR')
        response=self.client.post(self.url(),{'table':self.config.pk,'customer_name':'Ana','customer_phone':'55555555'})
        self.assertEqual(response.status_code,302)
        row=EventPurchase.objects.get();self.assertEqual(row.amount,600)
        self.assertEqual(row.tickets.count(),0)
        self.assertNotContains(self.client.get(self.url()),'name="table"')

    def test_expired_portal_removes_payment_and_timer(self):
        row=self.buy();EventPurchase.objects.filter(pk=row.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        page=self.client.get(reverse('event-public:portal',args=[row.secure_token]))
        self.assertContains(page,'El plazo terminó.')
        self.assertNotContains(page,'data-deadline=')
        self.assertNotContains(page,'Enviar comprobante')
        self.assertIn('noindex',page['X-Robots-Tag'])


class PublicReservationTests(ReservationCase):
    def search(self):
        return {'date':self.start.date().isoformat(),'time':self.start.strftime('%H:%M'),'party_size':4}

    def selection(self):
        response=self.client.get('/reservas/mesas/',self.search())
        return response.context['groups'][0]['tables'][0]['selection']

    def test_map_only_public_tables_safe_projection(self):
        VenueTable.objects.create(area=self.area,name='Mesa privada secreta',capacity=6,reservable_web=False)
        response=self.client.get('/reservas/mesas/',self.search())
        self.assertContains(response,'VIP 2');self.assertNotContains(response,'Mesa privada secreta')
        self.assertNotContains(response,'PENDING_REVIEW')
        self.assertTrue(response.context['groups'][0]['tables'][0]['available'])
        self.request()
        response=self.client.get('/reservas/mesas/',self.search())
        self.assertFalse(response.context['has_available'])
        self.assertContains(response,'No hay mesas disponibles')

    def test_two_sessions_single_hold_and_friendly_conflict(self):
        selection=self.selection()
        payload={'selection':selection,'customer_name':'Ana','customer_phone':'+502 5555 5555'}
        response=self.client.post('/reservas/datos/',payload)
        self.assertEqual(response.status_code,302)
        row=Reservation.objects.get();self.assertEqual(row.status,'PENDING_REVIEW')
        second=Client().post('/reservas/datos/',payload)
        self.assertEqual(second.status_code,409)
        self.assertContains(second,'ya no está disponible',status_code=409)
        self.assertEqual(Reservation.objects.count(),1)
        page=self.client.get(response.url)
        self.assertContains(page,'Solicitud recibida.');self.assertContains(page,'aún no está confirmada')
        self.assertNotContains(page,row.customer_phone)
        self.assertNotContains(page,'/entrada/')

    def test_bad_selection_and_invalid_dates(self):
        self.assertEqual(self.client.get('/reservas/datos/',{'selection':'tampered'}).status_code,409)
        page=self.client.get('/reservas/mesas/',{'date':'2000-01-01','time':'20:00','party_size':4})
        self.assertContains(page,'futuras')
        self.assertFalse(page.context['groups'])

    def test_disabled_reservations_and_capacity(self):
        ReservationSettings.objects.create(pk=1,reservations_enabled=False)
        self.assertNotContains(self.client.get('/reservas/'),'Ver mesas disponibles')
        self.assertFalse(self.client.get('/reservas/mesas/',self.search()).context['groups'])

    def test_payment_portal_upload_and_confirmation(self):
        row=self.approve(paid=True)
        url=reverse('reservation-client:detail',args=[row.secure_token])
        self.assertContains(self.client.get(url),'Confirma tu noche.')
        response=self.client.post(url,{'amount':300,'reference':'WEB-REF','proof_image':proof()})
        self.assertEqual(response.status_code,302)
        self.assertContains(self.client.get(url),'Recibimos tu comprobante.')
        row.refresh_from_db();reservations.confirm_reservation_payment(row.payment,self.manager)
        page=self.client.get(url)
        self.assertContains(page,'Tu mesa te espera.')
        self.assertNotContains(page,'data-deadline=')
        self.assertIn('no-store',page['Cache-Control'])

    def test_csrf_on_public_hold(self):
        response=Client(enforce_csrf_checks=True).post('/reservas/datos/',{'selection':self.selection()})
        self.assertEqual(response.status_code,403)

    def test_stored_expiry_no_countdown_and_no_payment_form(self):
        row=self.request()
        Reservation.objects.filter(pk=row.pk).update(status='EXPIRED')
        page=self.client.get(reverse('reservation-client:detail',args=[row.secure_token]))
        self.assertContains(page,'El plazo terminó.')
        self.assertNotContains(page,'data-deadline=')
