from datetime import timedelta
from pathlib import Path
from django.contrib import admin
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from apps.cash.services import open_business_day
from apps.reservations import services as s
from apps.reservations.models import Reservation, ReservationPayment, ReservationSettings
from apps.reservations.messages import whatsapp_url
from .base import ReservationCase, proof


class ViewTests(ReservationCase):
    def login(self, client=None):
        return (client or self.client).post('/gerencia/acceso/',{'username':self.manager.username,'password':'Test-3b-992!'})

    def url(self,row):
        return reverse('reservations:detail',args=[row.public_code])

    def public(self,row):
        return reverse('reservation-client:detail',args=[row.secure_token])

    def action(self,row,action,**data):
        response=self.client.get(self.url(row))
        return self.client.post(self.url(row),{'action':action,'confirmed':'yes',
            'confirmation':response.context[action.replace('-','_')+'_token'],**data})

    def test_anonymous_and_role_without_permission(self):
        self.assertRedirects(self.client.get('/gerencia/reservas/'),'/gerencia/acceso/')
        self.login();self.revoke('view_reservations')
        self.assertEqual(self.client.get('/gerencia/reservas/').status_code,403)

    def test_list_filters_search_effective_expiry(self):
        row=self.request();self.login()
        response=self.client.get('/gerencia/reservas/')
        self.assertContains(response,'Ana López'); self.assertEqual(response.context['counts']['pending'],1)
        self.assertEqual(response.context['counts']['review'],1)
        self.assertContains(response,'Necesitan atención')
        self.assertContains(self.client.get('/gerencia/reservas/?filter=attention'),'Ana López')
        self.assertContains(self.client.get('/gerencia/reservas/?q=BP-R-'),'Ana López')
        self.assertNotContains(self.client.get('/gerencia/reservas/?q=desconocido'),'Ana López')
        self.assertNotContains(self.client.get('/gerencia/reservas/?filter=CONFIRMED'),'Ana López')
        Reservation.objects.filter(pk=row.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertContains(self.client.get('/gerencia/reservas/'),'Expirada')
        self.assertNotContains(self.client.get('/gerencia/reservas/?filter=PENDING_REVIEW'),'Ana López')

    def test_review_and_approve_signed(self):
        row=self.request();self.login()
        self.assertContains(self.client.get(self.url(row)),'Revisar reserva')
        response=self.action(row,'approve',payment_type='FIXED',payment_value='0',payment_application='CREDIT')
        self.assertEqual(response.status_code,302)
        row.refresh_from_db();self.assertEqual(row.status,'CONFIRMED')

    def test_missing_confirmation_and_stale_action_rejected(self):
        row=self.request();self.login()
        response=self.client.get(self.url(row));token=response.context['approve_token']
        self.assertEqual(self.client.post(self.url(row),{'action':'approve'}).status_code,409)
        s.approve_reservation(row,self.manager,payment_required=False)
        self.assertEqual(self.client.post(self.url(row),{'action':'approve','confirmed':'yes','confirmation':token}).status_code,409)

    def test_action_permission_enforced_and_get_does_not_mutate(self):
        row=self.request();self.login();self.revoke('approve_reservation')
        self.assertNotContains(self.client.get(self.url(row)),'Aprobar reserva →')
        self.assertEqual(self.action(row,'approve').status_code,403)
        row.refresh_from_db();self.assertEqual(row.status,'PENDING_REVIEW')

    def test_client_only_own_reservation_no_ids_or_other_customer(self):
        row=self.request()
        other=self.request(start=self.start+timedelta(days=1))
        response=self.client.get(self.public(row))
        self.assertContains(response,row.public_code)
        self.assertNotContains(response,other.public_code)
        self.assertNotContains(response,row.customer_phone)
        self.assertNotContains(response,'name="reservation_id"')
        self.assertEqual(response['Referrer-Policy'],'same-origin')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertEqual(self.client.get('/reservas/r/'+row.public_code+'/').status_code,404)
        self.assertEqual(self.client.get('/reservas/r/1/').status_code,404)

    def test_client_payment_and_private_proof(self):
        row=self.approve(paid=True)
        response=self.client.post(self.public(row),{'amount':300,'reference':'CLIENT-300','proof_image':proof()})
        self.assertEqual(response.status_code,302)
        row.refresh_from_db();self.assertEqual(row.status,'PAYMENT_REVIEW')
        self.assertTrue(Path(row.payment.proof_image.path).is_relative_to(Path(self.storage.name).resolve()))
        with self.assertRaises(ValueError):
            _ = row.payment.proof_image.url
        url=reverse('reservations:proof',args=[row.public_code])
        self.assertEqual(self.client.get(url).status_code,302)
        self.login()
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'image/png')
        b''.join(response.streaming_content)
        self.assertNotContains(self.client.get(self.url(row)), '/media/')
        self.revoke('view_reservations')
        self.assertEqual(self.client.get(url).status_code,403)

    def test_invalid_upload_and_missing_proof_render_errors(self):
        row=self.approve(paid=True)
        response=self.client.post(self.public(row),{'amount':300,'reference':'R'})
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.context['form'].errors)
        row.refresh_from_db();self.assertEqual(row.status,'AWAITING_PAYMENT')

    def test_csrf_required_public_and_management(self):
        row=self.approve(paid=True)
        client=Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(self.public(row),{'amount':300,'reference':'R','proof_image':proof()}).status_code,403)
        self.assertEqual(client.post(self.url(row),{'action':'cancel'}).status_code,403)

    def test_payment_review_confirm_and_arrival(self):
        row=self.approve(paid=True)
        s.submit_reservation_payment(row,300,'R',proof())
        self.login()
        self.assertContains(self.client.get(self.url(row)),'Revisar pago de reserva')
        self.assertEqual(self.action(row,'verify').status_code,302)
        self.assertContains(self.client.get(self.url(row)),'Reserva confirmada')
        open_business_day(self.admin)
        self.assertEqual(self.action(row,'arrive',waiter=self.waiter.pk).status_code,302)
        self.assertContains(self.client.get(self.url(row)),'Mesa ocupada · Cuenta creada')

    def test_arrival_invalid_waiter_returns_validation(self):
        row=self.confirmed();self.login();open_business_day(self.admin)
        self.assertEqual(self.action(row,'arrive',waiter='garbage').status_code,409)

    def test_manual_and_settings_forms(self):
        self.login()
        create_page=self.client.get('/gerencia/reservas/nueva/')
        self.assertContains(create_page,'Crear reserva')
        self.assertContains(create_page,'¿A nombre de quién guardamos la mesa?')
        self.assertContains(create_page,'Guardar y ver reserva')
        self.assertNotContains(create_page,'VIP 2')
        self.assertContains(self.client.get('/gerencia/reservas/configuracion/'),'Configuración de reservas')
        response=self.client.post('/gerencia/reservas/nueva/',{'table':self.table.pk,'customer_name':'Pedro',
            'customer_phone':'+50255555555','date':str(self.start.date()),'time':'20:00','duration':180,'party_size':4,
            'payment_type':'FIXED','payment_value':0,'payment_application':'CREDIT'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(Reservation.objects.get(customer_name='Pedro').status,'CONFIRMED')

    @override_settings(PUBLIC_BASE_URL='https://reservas.example')
    def test_whatsapp_manual_url_secure_link_no_internal_reason(self):
        row=self.approve(paid=True)
        url=whatsapp_url(row)
        self.assertTrue(url.startswith('https://wa.me/50255555555?text='))
        self.assertIn('reservas.example',url)
        self.assertIn(row.secure_token,url)
        self.assertIn('300.00',url)
        row.status='REJECTED';row.rejection_reason='internal payment #7'
        self.assertNotIn('internal',whatsapp_url(row))

    def test_admin_readonly_no_mutations(self):
        from django.test import RequestFactory
        request=RequestFactory().get('/admin/');request.user=self.admin
        for model in (Reservation,ReservationPayment,ReservationSettings):
            model_admin=admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_valid_csrf_same_origin_and_foreign_origin_blocked(self):
        row=self.approve(paid=True)
        client=Client(enforce_csrf_checks=True)
        response=client.get(self.public(row))
        token=client.cookies['csrftoken'].value
        self.assertEqual(response['Referrer-Policy'],'same-origin')
        data={'amount':300,'reference':'R','csrfmiddlewaretoken':token,'proof_image':proof()}
        self.assertEqual(client.post(self.public(row),data,HTTP_ORIGIN='https://evil.example').status_code,403)
        data['proof_image']=proof()
        self.assertEqual(client.post(self.public(row),data,HTTP_ORIGIN='http://testserver').status_code,302)
