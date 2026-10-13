"""Gerencia usa sesiones separadas y los mismos servicios de cierre/pagos del POS."""
from datetime import timedelta
from decimal import Decimal as D
from importlib import import_module
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash import services as cash
from apps.cash.models import BusinessDay, BusinessDayReopen, CashSession
from apps.cash.tests.base import CashTestCase
from apps.orders import services as orders
from apps.orders.models import TableOrder
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.operations.management import queries
from apps.tables.models import VenueTable
from apps.venues.models import Area


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ManagementTests(CashTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.manager = get_user_model().objects.create_user(username='manager', password='Management-test-882!',
            role='GERENTE', first_name='Julia', last_name='Morales')
        cls.manager.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=['cash','payments','printing']))

    def setUp(self):
        self.login()

    def login(self, client=None, user=None):
        return (client or self.client).post('/gerencia/acceso/', {'username':(user or self.manager).username,
            'password':'Management-test-882!'})

    def revoke(self, permission):
        self.manager.user_permissions.remove(Permission.objects.get(codename=permission))
        for name in ('_perm_cache','_user_perm_cache','_group_perm_cache'):
            self.manager.__dict__.pop(name,None)

    def day_url(self, action='close-day', day=None):
        return reverse('management:'+action,args=[(day or self.day).pk])

    def payment_url(self, payment, day=None):
        return reverse('management:payment',args=[(day or self.day).pk,payment.pk])

    def day_post(self, action='close-day', **data):
        url = self.day_url(action)
        response = self.client.get(url)
        return self.client.post(url, {'confirmation':response.context['confirmation'],'confirmed':'yes',**data})

    def payment_post(self, payment, action='confirm', **data):
        url = self.payment_url(payment)
        response = self.client.get(url)
        return self.client.post(url, {'confirmation':response.context[action+'_token'],'confirmed':'yes','action':action,**data})

    def quick(self, session, quantity=2, method='CARD'):
        # Build the same domain object and send/payment sequence used by Caja; no presentation mocks.
        order = TableOrder.objects.create(order_type='QUICK_SALE',area=session.register.area,business_day=self.day,
            cash_session=session,opened_by=self.user,responsible_waiter=self.user)
        orders.add_product_to_order(order,self.product,quantity,self.user)
        orders.send_order(order,self.user,fulfillment_mode='TAKE_AT_BAR',defer_ticket=True)
        payment = self.payment(order,str(quantity*25),session=session if method=='CASH' else None,method=method)
        if method in ('CASH','CARD'):
            payments.close_order(order,self.user)
        return order,payment

    def test_manager_and_owner_login_without_staff(self):
        self.assertFalse(self.manager.is_staff)
        self.assertContains(self.client.get('/gerencia/'),'¿Qué necesitas hacer?')
        self.manager.role='PROPIETARIO'; self.manager.save()
        self.assertEqual(self.login().status_code,302)
        self.assertContains(self.client.get('/gerencia/'),'Propietario')

    def test_wrong_role_password_inactive_and_anonymous(self):
        for role in ['MESERO','CAJERO']:
            self.manager.role=role; self.manager.save()
            self.assertEqual(self.login().status_code,400)
            self.assertRedirects(self.client.get('/gerencia/'),'/gerencia/acceso/')
        self.manager.role='GERENTE'; self.manager.is_active=False; self.manager.save()
        self.assertEqual(self.login().status_code,400)
        self.assertEqual(Client().post('/gerencia/acceso/',{'username':'manager','password':'wrong'}).status_code,400)
        self.assertRedirects(Client().get('/gerencia/cierres/'),'/gerencia/acceso/')

    def test_admin_login_does_not_grant_management_access(self):
        client=Client(); client.force_login(self.manager)
        self.assertRedirects(client.get('/gerencia/'),'/gerencia/acceso/')

    def test_management_session_independent_cookie_and_logout(self):
        self.client.force_login(self.user)
        admin_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.login()
        cookie=self.client.cookies[settings.MANAGEMENT_SESSION_COOKIE_NAME]
        self.assertEqual(cookie['path'],'/gerencia/')
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'],'Lax')
        self.assertNotEqual(cookie.value,admin_key)
        self.client.post('/gerencia/salir/')
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value,admin_key)
        self.assertContains(self.client.get('/admin/'),'Administración')
        self.assertRedirects(self.client.get('/gerencia/'),'/gerencia/acceso/')

    def test_management_login_does_not_create_admin_session(self):
        self.assertNotIn(settings.SESSION_COOKIE_NAME,self.client.cookies)
        self.assertEqual(self.client.get('/admin/').status_code,302)

    def test_timeout_enforced_server_side_and_activity_returns_401(self):
        store=import_module(settings.SESSION_ENGINE).SessionStore(self.client.cookies[settings.MANAGEMENT_SESSION_COOKIE_NAME].value)
        store['management_last_activity']=timezone.now().timestamp()-1801; store.save()
        response=self.client.post('/gerencia/actividad/',HTTP_ACCEPT='application/json')
        self.assertEqual(response.status_code,401)
        self.assertEqual(response.json()['next'],'/gerencia/acceso/')
        self.assertRedirects(self.client.get('/gerencia/'),'/gerencia/acceso/')

    def test_role_revocation_takes_effect_on_next_request(self):
        self.manager.role='CAJERO'; self.manager.save()
        self.assertRedirects(self.client.get('/gerencia/'),'/gerencia/acceso/')

    def test_manager_has_no_day_actions(self):
        cash.close_business_day(self.day,self.user)
        response=self.client.get('/gerencia/')
        self.assertContains(response,'Todavía no hay cajas en operación')
        self.assertNotContains(response,'Abrir jornada')
        self.assertFalse(BusinessDay.objects.filter(status='OPEN').exists())
        for method in ('get','post'):
            for url in ['/gerencia/jornada/abrir/',self.day_url(),self.day_url('reopen-day')]:
                self.assertRedirects(getattr(self.client,method)(url),'/gerencia/cierres/')
        self.day.refresh_from_db()
        self.assertEqual(self.day.status,'CLOSED')

    def test_current_day_scope_excludes_other_day_even_when_calendar_overlaps(self):
        old=self.day
        cash.close_business_day(old,self.user)
        self.day=cash.open_business_day(self.user,old.business_date+timedelta(days=1))
        order,_=self.consumption()
        self.payment(order,method='CARD')
        response=self.client.get('/gerencia/')
        self.assertEqual(response.context['day'].pk,self.day.pk)
        self.assertEqual(response.context['summary']['gross_sales'],D('100'))
        self.assertEqual(response.context['confirmed_net'],D('25'))

    def test_dashboard_multitable_and_separate_pending_collection(self):
        order,_=self.consumption()
        orders.join_table_to_order(order,self.destination,self.user)
        self.payment(order,'25',method='CARD')
        self.payment(order,'50',method='TRANSFER')
        response=self.client.get('/gerencia/')
        self.assertEqual(response.context['occupied_tables'],2)
        self.assertEqual(response.context['summary']['net_sales'],D('100'))
        self.assertEqual(response.context['confirmed_net'],D('25'))
        from apps.printing.models import PrintJob
        self.assertEqual(response.context['pending_count'],1+PrintJob.objects.filter(order__business_day=self.day,status='FAILED').count())
        self.assertEqual(response.context['summary']['payments_by_method']['TRANSFER']['pending'],D('50'))
        self.assertEqual(sum(p['value'] for p in response.context['hourly']['points']),D('25'))

    def test_gross_adjustments_refunds_and_fully_refunded_methods(self):
        order,_=self.consumption()
        payments.apply_order_adjustment(order,self.user,amount=D('10'),reason='Cortesía')
        card=self.payment(order,'50',method='CARD')
        payments.refund_payment(card,self.user,amount=D('20'),reason='Devolución parcial')
        response=self.client.get('/gerencia/')
        summary=response.context['summary']
        self.assertEqual([summary[k] for k in ('gross_sales','adjustments','refunds','net_sales')],[D('100'),D('10'),D('20'),D('70')])
        self.assertEqual(response.context['confirmed_net'],D('30'))
        self.assertEqual(response.context['areas'][0]['total'],D('70'))
        payments.refund_payment(card,self.user,amount=D('30'),reason='Devolución restante')
        data=self.client.get('/gerencia/').context
        self.assertEqual(data['confirmed_net'],D('0'))
        self.assertEqual(data['summary']['payments_by_method']['CARD']['refunds'],D('50'))

    def test_quick_sales_included_in_area_hour_methods_and_cash_detail(self):
        session=self.session()
        order,payment=self.quick(session)
        response=self.client.get('/gerencia/')
        self.assertEqual(response.context['summary']['net_sales'],D('50'))
        self.assertEqual(response.context['confirmed_net'],D('50'))
        self.assertEqual(response.context['occupied_tables'],0)
        self.assertEqual(response.context['areas'][0]['total'],D('50'))
        response=self.client.get(reverse('management:cash-detail',args=[self.day.pk,session.pk]))
        self.assertEqual(response.context['associated_sales'],D('50'))

    def test_hour_chart_uses_day_not_midnight_and_never_pending(self):
        order,_=self.consumption()
        first=self.payment(order,'25',method='CARD'); second=self.payment(order,'25',method='CARD')
        self.payment(order,'25',method='DEPOSIT')
        start=timezone.now().replace(hour=23,minute=30,second=0)
        Payment.objects.filter(pk=first.pk).update(confirmed_at=start)
        Payment.objects.filter(pk=second.pk).update(confirmed_at=start+timedelta(hours=2))
        data=self.client.get('/gerencia/').context
        self.assertEqual(len(data['hourly']['points']),3)
        self.assertEqual(data['hourly']['points'][1]['value'],D('0'))
        self.assertEqual(sum(p['value'] for p in data['hourly']['points']),D('50'))

    def test_attention_limits_five_and_includes_failed_print_and_handoff(self):
        from apps.printing.models import PrintJob
        order,_=self.consumption(10)
        for i in range(6): self.payment(order,'10',method='TRANSFER')
        self.payment(order,'25')
        PrintJob.objects.create(order=order,job_type='RECEIPT',status='FAILED',payload_snapshot={'destination':'Cocina'})
        data=self.client.get('/gerencia/').context
        self.assertEqual(len(data['attention']),5)
        self.assertEqual(data['pending_count'],7+PrintJob.objects.filter(order__business_day=self.day,status='FAILED').count())

    def test_three_registers_open_closed_and_cash_difference(self):
        disco=Area.objects.create(name='Discoteca',slug='discoteca')
        a=self.session(); b=self.session(register=self.register('DISCO',disco)); c=self.session(register=self.register('PREMIUM',self.other_area))
        self.close_session(c,'80','Faltante investigado')
        response=self.client.get('/gerencia/cierres/')
        self.assertEqual(len(response.context['registers']),3)
        self.assertEqual(response.context['summary']['sessions'],{'open':2,'closed':1})
        self.assertEqual(response.context['difference_count'],1)
        self.assertContains(response,'Revisar caja abierta',count=2)
        self.assertContains(response,'Ver resultado del cierre')
        self.assertContains(response,'Turnos registrados')
        response=self.client.get(reverse('management:cash-detail',args=[self.day.pk,c.pk]))
        self.assertContains(response,'Faltante Q20')
        self.assertContains(response,'Faltante investigado')
        self.assertContains(response,'Efectivo contado')

    def test_multiple_sessions_of_register_are_all_accessible(self):
        first=self.session(); self.close_session(first)
        second=self.session(register=first.register)
        response=self.client.get('/gerencia/cierres/')
        self.assertEqual(response.context['registers'][0]['session'].pk,second.pk)
        self.assertEqual(len(response.context['session_rows']),2)
        self.assertContains(response,reverse('management:cash-detail',args=[self.day.pk,first.pk]))

    def test_financial_permission_hides_amounts_in_all_financial_views(self):
        session=self.session('9876.54')
        order,_=self.consumption()
        self.revoke('view_cash_session_financials')
        for url in ['/gerencia/','/gerencia/cierres/',reverse('management:cash-detail',args=[self.day.pk,session.pk])]:
            with self.subTest(url=url):
                response=self.client.get(url)
                self.assertEqual(response.status_code,200)
                self.assertNotContains(response,'9876')
                self.assertNotContains(response,'Q100')
                self.assertNotContains(response,'Q100,00')
                self.assertNotContains(response,'Q100.00')

    def test_open_cash_detail_movements_handoffs_withdrawals_readonly(self):
        session=self.session(); order,_=self.consumption()
        self.payment(order,session=session)
        self.payment(order)
        cash.create_cash_withdrawal(session,D('10'),'Bóveda',self.user,self.user)
        response=self.client.get(reverse('management:cash-detail',args=[self.day.pk,session.pk]))
        self.assertEqual(response.context['financial']['expected_cash'],D('115'))
        self.assertEqual(len(response.context['movements']),2)
        self.assertEqual(len(response.context['pending_handoffs']),1)
        self.assertEqual(self.client.post(response.request['PATH_INFO']).status_code,405)

    def test_pending_operations_visible_without_general_close(self):
        self.session(); order,_=self.consumption()
        self.payment(order,method='TRANSFER'); self.payment(order)
        response=self.client.get('/gerencia/cierres/')
        kinds={b['type'] for b in response.context['blockers']}
        self.assertTrue({'ACTIVE_ORDER','OUTSTANDING_BALANCE','PENDING_PAYMENT','PENDING_HANDOFF','OPEN_CASH_SESSION'}<=kinds)
        self.assertNotContains(response,'Cerrar jornada')
        self.assertContains(response,'No hay un cierre general obligatorio')
        self.assertRedirects(self.client.post(self.day_url()),'/gerencia/cierres/')
        self.day.refresh_from_db(); self.assertEqual(self.day.status,'OPEN')

    def test_pending_list_transfer_deposit_and_empty_state(self):
        self.assertContains(self.client.get('/gerencia/pagos-pendientes/'),'No hay transferencias ni depósitos pendientes')
        order,_=self.consumption()
        transfer=self.payment(order,method='TRANSFER'); deposit=self.payment(order,method='DEPOSIT'); self.payment(order,method='CARD')
        response=self.client.get('/gerencia/pagos-pendientes/')
        self.assertEqual({p.pk for p in response.context['payments']},{transfer.pk,deposit.pk})
        self.assertContains(response,'REF',count=2)

    def test_confirm_transfer_and_deposit_refresh_account(self):
        order,_=self.consumption()
        for method in ('TRANSFER','DEPOSIT'):
            payment=self.payment(order,'50',method=method)
            response=self.payment_post(payment)
            self.assertRedirects(response,self.payment_url(payment))
            payment.refresh_from_db(); self.assertEqual(payment.status,'CONFIRMED')
            self.assertEqual(payment.confirmed_by,self.manager)
        order.refresh_from_db(); self.assertEqual(order.status,'PARTIALLY_PAID')
        self.assertEqual(payments.get_order_confirmed_paid_total(order),D('100'))

    def test_reject_requires_reason_retains_payment_and_releases_balance(self):
        order,_=self.consumption(); payment=self.payment(order,method='DEPOSIT')
        self.assertEqual(self.payment_post(payment,'reject',reason=' ').status_code,409)
        self.assertRedirects(self.payment_post(payment,'reject',reason='Referencia incorrecta'),self.payment_url(payment))
        payment.refresh_from_db(); self.assertEqual(payment.status,'REJECTED')
        self.assertEqual(payment.metadata['rejection_reason'],'Referencia incorrecta')
        self.assertContains(self.client.get(self.payment_url(payment)),'Referencia incorrecta')
        self.assertEqual(payments.get_order_pending_payment_total(order),D('0'))

    def test_confirm_and_reject_separate_permissions(self):
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        self.revoke('verify_transfer_payment')
        self.assertEqual(self.payment_post(payment).status_code,403)
        self.assertRedirects(self.payment_post(payment,'reject',reason='No recibido'),self.payment_url(payment))
        payment=self.payment(order,method='DEPOSIT')
        self.revoke('reject_transfer_payment')
        self.assertEqual(self.payment_post(payment,'reject',reason='No recibido').status_code,403)
        self.revoke('view_payment')
        self.assertEqual(self.client.get('/gerencia/pagos-pendientes/').status_code,403)
        self.assertEqual(self.client.get(self.payment_url(payment)).status_code,403)

    def test_stale_confirmation_rejected_after_payment_change(self):
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        url=self.payment_url(payment); token=self.client.get(url).context['confirm_token']
        payments.reject_pending_payment(payment,self.user,'Revisado por otro gerente')
        response=self.client.post(url,{'confirmation':token,'action':'confirm','confirmed':'yes'})
        self.assertEqual(response.status_code,409)
        payment.refresh_from_db(); self.assertEqual(payment.status,'REJECTED')

    def test_confirmation_expires_and_cannot_cross_action_or_session(self):
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        url=self.payment_url(payment); token=self.client.get(url).context['confirm_token']
        self.assertEqual(self.client.post(url,{'confirmation':token,'action':'reject','confirmed':'yes','reason':'Cambio'}).status_code,409)
        other=Client(); self.login(other)
        self.assertEqual(other.post(url,{'confirmation':token,'action':'confirm','confirmed':'yes'}).status_code,409)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+601):
            self.assertEqual(self.client.post(url,{'confirmation':token,'action':'confirm','confirmed':'yes'}).status_code,409)

    def test_double_confirmation_only_changes_payment_once(self):
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        url=self.payment_url(payment); token=self.client.get(url).context['confirm_token']
        data={'confirmation':token,'action':'confirm','confirmed':'yes'}
        self.assertEqual(self.client.post(url,data).status_code,302)
        self.assertEqual(self.client.post(url,data).status_code,409)
        self.assertEqual(order.activities.filter(activity_type='PAYMENT_CONFIRMED').count(),1)

    def test_payment_and_session_ids_are_scoped_to_day(self):
        session=self.session(); order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        other=BusinessDay.objects.create(business_date=self.day.business_date-timedelta(days=1),status='CLOSED',
            opened_by=self.user,closed_by=self.user,closed_at=timezone.now())
        self.assertEqual(self.client.get(self.payment_url(payment,other)).status_code,404)
        self.assertEqual(self.client.post(self.payment_url(payment,other),{'action':'confirm'}).status_code,404)
        self.assertEqual(self.client.get(reverse('management:cash-detail',args=[other.pk,session.pk])).status_code,404)
        self.assertEqual(self.client.get('/gerencia/cierres/?jornada=bad').status_code,404)
        self.assertEqual(self.client.get('/gerencia/cierres/?jornada=-1').status_code,404)

    def test_csrf_mutations_and_gets_never_mutate(self):
        protected=Client(enforce_csrf_checks=True); protected.cookies.update(self.client.cookies)
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        for url in [self.day_url(),'/gerencia/jornada/abrir/',self.payment_url(payment),'/gerencia/salir/','/gerencia/actividad/']:
            self.assertEqual(protected.post(url).status_code,403)
        self.assertEqual(self.client.get('/gerencia/salir/').status_code,405)
        self.assertEqual(self.client.get('/gerencia/actividad/').status_code,405)
        payment.refresh_from_db(); self.assertEqual(payment.status,'PENDING')
        self.day.refresh_from_db(); self.assertEqual(self.day.status,'OPEN')

    def test_closed_day_rejects_payment_mutation(self):
        order,_=self.consumption(); payment=self.payment(order,method='TRANSFER')
        token=self.client.get(self.payment_url(payment)).context['confirm_token']
        BusinessDay.objects.filter(pk=self.day.pk).update(status='CLOSED',closed_at=timezone.now(),closed_by=self.user)
        response=self.client.post(self.payment_url(payment),{'confirmation':token,'confirmed':'yes','action':'confirm'})
        self.assertEqual(response.status_code,409)
        payment.refresh_from_db(); self.assertEqual(payment.status,'PENDING')

    def test_print_history_reuses_existing_module_and_permissions(self):
        self.assertContains(self.client.get('/gerencia/impresiones/'),'Impresiones')
        self.revoke('manage_printers')
        self.assertContains(self.client.get('/gerencia/impresiones/'),'Impresiones')
        self.assertEqual(self.client.post('/gerencia/impresiones/1/retry/').status_code,403)
        self.revoke('view_printjob')
        self.assertEqual(self.client.get('/gerencia/impresiones/').status_code,403)

    def test_query_count_does_not_grow_per_order_payment_or_table(self):
        def add(index):
            table=VenueTable.objects.create(area=self.area,name=f'Mesa P{index}',capacity=4)
            order=self.open(table); orders.add_product_to_order(order,self.product,1,self.user); orders.send_order(order,self.user)
            payment=self.payment(order,'25',method='CARD')
            payments.refund_payment(payment,self.user,amount=D('5'),reason='Ajuste')
        add(0)
        # Warm auth permission cache so each measurement covers the same workload.
        queries.dashboard(self.day,self.manager)
        with CaptureQueriesContext(connection) as small: queries.dashboard(self.day,self.manager)
        for index in range(1,9): add(index)
        with CaptureQueriesContext(connection) as large: queries.dashboard(self.day,self.manager)
        self.assertLessEqual(len(large),len(small)+2, '\n'.join(q['sql'] for q in large.captured_queries))
        self.assertLessEqual(len(large),35)

    def test_inactive_area_sales_remain_in_historical_day_totals(self):
        session=self.session(register=self.register('PREMIUM',self.other_area))
        self.quick(session)
        Area.objects.filter(pk=self.other_area.pk).update(is_active=False)
        data=queries.dashboard(self.day,self.manager)
        self.assertEqual(sum(row['total'] for row in data['areas']),data['summary']['net_sales'])
        self.assertEqual(next(row['total'] for row in data['areas'] if row['name']=='Premium'),D('50'))

    def test_incidents_show_cash_reason_without_becoming_close_blockers(self):
        session=self.session(); self.close_session(session,'80','Diferencia documentada')
        response=self.client.get('/gerencia/cierres/')
        self.assertEqual(response.context['blockers'],[])
        self.assertContains(response,'Diferencia documentada')
        self.assertRedirects(self.client.post(self.day_url()), '/gerencia/cierres/')
        self.revoke('view_cash_session_financials')
        response=self.client.get(self.day_url('day-result'))
        self.assertNotContains(response,'Q20')
        self.assertNotContains(response,'Diferencia documentada')
