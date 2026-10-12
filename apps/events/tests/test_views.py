import json
from pathlib import Path
from datetime import timedelta
from django.contrib import admin
from django.test import Client, override_settings
from django.urls import reverse
from apps.events import services as s
from apps.events.models import Event, EventTicket, EventPurchase
from .base import EventCase, picture


class ViewTests(EventCase):
    def login(self, client=None):
        return (client or self.client).post('/gerencia/acceso/',{'username':self.manager.username,'password':'Event-Test-32!'})

    def portal_url(self,row):
        return reverse('event-public:portal',args=[row.secure_token])

    def test_management_requires_login_and_permission(self):
        self.assertRedirects(self.client.get('/gerencia/eventos/'),'/gerencia/acceso/')
        self.login();self.revoke('view_events')
        self.assertEqual(self.client.get('/gerencia/eventos/').status_code,403)

    def test_list_detail_filters_and_wizard_render(self):
        self.login()
        self.assertContains(self.client.get('/gerencia/eventos/'),'Noche Especial')
        self.assertNotContains(self.client.get('/gerencia/eventos/?filter=DRAFT'),'Noche Especial')
        self.assertNotContains(self.client.get('/gerencia/eventos/?q=missing'),'Noche Especial')
        for step in range(1,5):self.assertEqual(self.client.get(reverse('events:wizard',args=[self.event.pk,step])).status_code,200)
        self.assertContains(self.client.get(reverse('events:detail',args=[self.event.pk])),'Aforo presente')
        self.assertEqual(self.client.get(reverse('events:wizard',args=[self.event.pk,8])).status_code,404)

    def test_create_draft_from_step_one(self):
        self.login()
        response=self.client.post('/gerencia/eventos/nuevo/',dict(name='Evento UI',starts_at=self.start.isoformat(),ends_at=(self.start+timedelta(hours=6)).isoformat(),image=picture(),ticket_sales_enabled='on'))
        self.assertEqual(response.status_code,302)
        row=Event.objects.get(name='Evento UI');self.assertEqual(row.status,'DRAFT')

    def test_no_capacity_or_purchase_information_without_permissions(self):
        self.login();self.revoke('view_event_capacity');self.revoke('view_event_purchases')
        page=self.client.get(reverse('events:detail',args=[self.event.pk]))
        self.assertNotContains(page,'Aforo presente');self.assertNotContains(page,'Compras por verificar')
        self.assertEqual(self.client.get(reverse('events:purchases',args=[self.event.pk])).status_code,403)

    def test_public_only_live_events(self):
        draft=s.duplicate_event(self.event,self.manager)
        self.assertEqual(self.client.get(reverse('event-public:event',args=[draft.slug])).status_code,404)
        self.assertContains(self.client.get(reverse('event-public:event',args=[self.event.slug])),'Elige tus entradas')
        s.cancel_event(self.event,self.manager,'Cancelado')
        self.assertEqual(self.client.get(reverse('event-public:event',args=[self.event.slug])).status_code,404)

    def test_published_event_can_return_to_draft_without_committed_purchases(self):
        self.login(); url=reverse('events:detail',args=[self.event.pk])
        page=self.client.get(url)
        self.assertContains(page,'Hacer evento privado')
        response=self.client.post(url,{'action':'unpublish','confirmed':'yes'})
        self.assertEqual(response.status_code,302)
        self.event.refresh_from_db();self.assertEqual(self.event.status,'DRAFT')
        self.assertEqual(self.client.get(reverse('event-public:event',args=[self.event.slug])).status_code,404)

    def test_event_with_active_purchase_cannot_return_to_draft(self):
        self.buy();self.login();url=reverse('events:detail',args=[self.event.pk])
        response=self.client.post(url,{'action':'unpublish','confirmed':'yes'})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'compras activas o confirmadas')
        self.event.refresh_from_db();self.assertEqual(self.event.status,'PUBLISHED')

    def test_public_mixed_purchase_post(self):
        response=self.client.post(reverse('event-public:event',args=[self.event.slug]),{f'qty_{self.general.pk}':'2',f'qty_{self.vip.pk}':'1','customer_name':'Ana','customer_phone':'55555555'})
        self.assertEqual(response.status_code,302);row=EventPurchase.objects.get();self.assertEqual(row.amount,350)
        self.assertRedirects(response,self.portal_url(row))

    def test_portal_isolation_and_headers(self):
        row=self.buy();other=self.buy()
        page=self.client.get(self.portal_url(row))
        self.assertContains(page,row.public_code);self.assertNotContains(page,other.public_code)
        self.assertIn('no-store',page['Cache-Control']);self.assertEqual(page['Referrer-Policy'],'same-origin')
        self.assertEqual(self.client.get('/eventos/compra/'+row.public_code+'/').status_code,404)

    def test_submit_payment_and_proof_permission(self):
        row=self.buy()
        response=self.client.post(self.portal_url(row),{'amount':200,'reference':'REF','proof_image':picture()})
        self.assertEqual(response.status_code,302);row.refresh_from_db();self.assertEqual(row.status,'PAYMENT_REVIEW')
        url=reverse('events:proof',args=[row.public_code]);self.assertEqual(self.client.get(url).status_code,302)
        self.login();response=self.client.get(url);self.assertEqual(response['Content-Type'],'image/png');b''.join(response.streaming_content)
        self.revoke('view_event_purchases');self.assertEqual(self.client.get(url).status_code,403)

    def test_payment_review_signed_confirmation(self):
        payment=self.submit();row=payment.purchase;self.login()
        url=reverse('events:purchase',args=[row.public_code]);page=self.client.get(url)
        self.assertContains(page,'Monto declarado')
        self.client.post(url,{'action':'confirm'})
        self.assertEqual(row.tickets.count(),0)
        response=self.client.post(url,{'action':'confirm','confirmed':'yes','confirmation':page.context['confirm_token']})
        self.assertEqual(response.status_code,302);self.assertEqual(row.tickets.count(),2)
        self.assertContains(self.client.get(url),'Enviar entradas por WhatsApp')

    def test_tickets_portal_pdf_and_qr_no_portal_grant(self):
        tickets=self.confirm();row=tickets[0].purchase
        page=self.client.get(self.portal_url(row));self.assertContains(page,'Descargar todas')
        for ticket in tickets:
            qr_page=self.client.get(reverse('event-access:ticket',args=[ticket.qr_token]))
            self.assertNotContains(qr_page,row.secure_token);self.assertNotContains(qr_page,row.customer_name);self.assertNotContains(qr_page,row.customer_phone)
            self.assertEqual(self.client.get('/eventos/compra/'+ticket.qr_token+'/').status_code,404)
        response=self.client.get(reverse('event-public:all-pdf',args=[row.secure_token]))
        self.assertEqual(response['Content-Type'],'application/pdf');self.assertTrue(b''.join(response.streaming_content).startswith(b'%PDF'))
        other=self.confirm()[0]
        self.assertEqual(self.client.get(reverse('event-public:pdf',args=[row.secure_token,other.ticket_number])).status_code,404)

    def test_pending_purchase_cannot_download_pdf(self):
        row=self.buy();self.assertEqual(self.client.get(reverse('event-public:all-pdf',args=[row.secure_token])).status_code,404)

    def test_cancelled_event_visible_portal_and_tickets(self):
        ticket=self.confirm()[0];s.cancel_event(self.event,self.manager,'Cancelado')
        self.assertContains(self.client.get(self.portal_url(ticket.purchase)),'Evento cancelado')
        self.assertContains(self.client.get(reverse('event-access:ticket',args=[ticket.qr_token])),'Cancelada')

    def test_csrf_public_management_guard(self):
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse('event-public:event',args=[self.event.slug]),{}).status_code,403)
        self.assertEqual(client.post('/acceso/ingresar/',{}).status_code,403)
        self.assertEqual(client.post('/gerencia/eventos/nuevo/',{}).status_code,403)

    def test_guard_pin_login_scan_and_isolation(self):
        self.assertRedirects(self.client.get('/acceso/'),'/acceso/ingresar/')
        response=self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'})
        self.assertEqual(response.status_code,302);self.assertIn('bigparty_access',response.cookies)
        self.assertEqual(response.cookies['bigparty_access']['path'],'/acceso/')
        self.assertEqual(self.client.get('/gerencia/eventos/').status_code,302)
        ticket=self.confirm()[0]
        url='/acceso/escanear/'
        response=self.client.post(url,json.dumps({'token':ticket.qr_token}),content_type='application/json')
        self.assertEqual(response.json()['result'],'VALID')
        self.assertEqual(self.client.post(url,json.dumps({'token':ticket.qr_token}),content_type='application/json').json()['result'],'USED')
        self.assertNotIn('Ana',response.content.decode())

    def test_guard_pin_throttle(self):
        for _ in range(5):self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'000000'})
        self.assertEqual(self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'}).status_code,200)
        self.assertEqual(self.client.get('/acceso/').status_code,302)

    def test_guard_permission_revocation_checked_each_request(self):
        self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'})
        self.guard.user_permissions.clear()
        self.assertEqual(self.client.post('/acceso/escanear/',json.dumps({'token':'x'}),content_type='application/json').status_code,401)

    @override_settings(DEBUG=False)
    def test_production_has_no_manual_token_field(self):
        self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'})
        page=self.client.get('/acceso/');self.assertContains(page,'Activar cámara');self.assertNotContains(page,'dev-token')

    def test_scanner_only_accepts_own_url(self):
        from apps.events.documents import ticket_url
        ticket=self.confirm()[0]
        self.client.post('/acceso/ingresar/',{'username':self.guard.username,'pin':'123456'})
        url='/acceso/escanear/'
        foreign='https://evil.example/entrada/'+ticket.qr_token+'/'
        self.assertEqual(self.client.post(url,json.dumps({'token':foreign}),content_type='application/json').json()['result'],'INVALID')
        self.assertEqual(self.client.post(url,json.dumps({'token':ticket_url(ticket)}),content_type='application/json').json()['result'],'VALID')

    def test_admin_sensitive_models_readonly(self):
        from django.test import RequestFactory
        request=RequestFactory().get('/admin/');request.user=self.manager
        for model in [Event,EventTicket,EventPurchase]:
            registered=admin.site._registry[model]
            self.assertFalse(registered.has_change_permission(request));self.assertFalse(registered.has_delete_permission(request));self.assertFalse(registered.has_add_permission(request))

    def test_historical_sales_remain_after_cancellation(self):
        self.confirm();s.cancel_event(self.event,self.manager,'Cancelado');self.login()
        self.assertEqual(self.client.get('/gerencia/eventos/').context['counts']['sold'],2)
        self.assertEqual(self.client.get(reverse('events:detail',args=[self.event.pk])).context['sold_count'],2)

    def test_courtesy_post_redirect_prevents_refresh_resubmit_and_retains_list(self):
        self.login();url=reverse('events:detail',args=[self.event.pk])
        response=self.client.post(url,{'action':'courtesy','ticket_type':self.courtesy.pk,'quantity':'2','confirmed':'yes'})
        self.assertEqual(response.status_code,302)
        for _ in range(2):self.assertContains(self.client.get(response.url),'Descargar PDF')
        self.assertEqual(self.event.tickets.count(),2)
