from datetime import timedelta
from decimal import Decimal as D
from io import BytesIO
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.utils import timezone
from django.template.loader import render_to_string
from apps.audit.models import AuditLog
from apps.cash.tests.base import CashTestCase
from apps.cash.models import BusinessDay
from apps.orders import services as orders
from apps.orders.models import TableOrder, OrderLine, OrderTableLink
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.core.models import BusinessSettings, PaymentMethodSettings, BankTransferSettings
from apps.core import configuration as config
from apps.operations.management import report_queries as reports
from apps.operations.management.audit_views import visible_data


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ReportsConfigurationTests(CashTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.manager = get_user_model().objects.create_user(username='manager3e', password='Report-test-882!', role='GERENTE', first_name='Julia', last_name='Morales')
        cls.manager.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=['core','audit','reservations','events','printing','accounts']))

    def setUp(self):
        self.client.post('/gerencia/acceso/', {'username':self.manager.username, 'password':'Report-test-882!'})

    def period(self):
        return reports.Period({'period':'current'})

    def test_financial_semantics_and_allocations(self):
        order, line = self.consumption(4)
        payments.apply_order_adjustment(order, self.user, amount=D('10'), reason='Promoción')
        payment = self.payment(order, '50', method='CARD')
        payments.refund_payment(payment, self.user, amount=D('5'), reason='Devolución parcial')
        self.payment(order, '20', method='TRANSFER')
        values = reports.commercial_totals(self.period())
        self.assertEqual(values, dict(gross=D('100'), adjustments=D('10'), refunds=D('5'), net=D('85'), confirmed=D('45'), pending=D('20'), credit=D('0'), balance=D('40')))
        product = reports.products(self.period())['rows'][0]
        self.assertEqual(product[2:], [4,'Q100.00','Q10.00','Q5.00','Q85.00'])

    def test_business_day_after_midnight_and_range(self):
        order, line = self.consumption()
        yesterday = timezone.localdate()-timedelta(days=1)
        BusinessDay.objects.filter(pk=self.day.pk).update(business_date=yesterday)
        self.assertEqual(reports.commercial_totals(self.period())['gross'], D('100'))
        specific = reports.Period({'period':'day','start':yesterday,'end':yesterday})
        self.assertEqual(reports.commercial_totals(specific)['gross'], D('100'))
        today = timezone.localdate()
        other = reports.Period({'period':'day','start':today,'end':today})
        self.assertEqual(reports.commercial_totals(other)['gross'], D('0'))
        ranged = reports.Period({'period':'range','start':yesterday,'end':today})
        self.assertEqual(reports.commercial_totals(ranged)['gross'], D('100'))

    def test_period_validation(self):
        today=timezone.localdate()
        for params in ({'period':'range','start':today,'end':today+timedelta(days=93)}, {'period':'day'}, {'period':'bad'}, {'period':'range','start':today,'end':today-timedelta(days=1)}):
            self.assertFalse(reports.PeriodForm(params).is_valid())

    def test_cancelled_and_combo(self):
        order, line = self.consumption(2)
        orders.cancel_sent_line(line, self.user, reason='Error de captura')
        combo, _ = self.combo()
        orders.add_product_to_order(order, combo, 2, self.user)
        orders.send_order(order, self.user)
        rows=reports.products(self.period())['rows']
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0][0], 'Combo')
        self.assertEqual(rows[0][2], 2)
        self.assertEqual(reports.commercial_totals(self.period())['gross'],D('200'))
        cancelled=reports.cancellations(self.period())[0]['rows'][0]
        self.assertEqual(cancelled[-1], 'Sí')

    def test_area_includes_quick_sale_and_table(self):
        self.consumption(2)
        session=self.session()
        order=TableOrder.objects.create(order_type='QUICK_SALE', area=self.area, business_day=self.day, cash_session=session, opened_by=self.user, responsible_waiter=self.user)
        orders.add_product_to_order(order,self.product,1,self.user)
        orders.send_order(order,self.user,fulfillment_mode="TAKE_AT_BAR",defer_ticket=True)
        row=reports.areas(self.period())['rows'][0]
        self.assertEqual(row[1:4], [2,1,'Q75.00'])

    def test_responsibility_and_payment_actor_are_distinct(self):
        order,_=self.consumption(2)
        TableOrder.objects.filter(pk=order.pk).update(responsible_waiter=self.other_user)
        self.payment(order,'25',method='CARD')
        rows=reports.waiters(self.period())
        self.assertEqual(rows[0]['rows'][0][0],self.other_user.username)
        self.assertEqual(rows[1]['rows'][0][0],self.user.username)
        self.assertEqual(rows[0]['rows'][0][1],1)

    def test_cash_expected_counted_difference_withdrawal(self):
        from apps.cash import services as cash
        session=self.session()
        order,_=self.consumption(2)
        self.payment(order,'50',session=session)
        cash.create_cash_withdrawal(session,D('20'),'Compra de hielo',self.user,self.other_user)
        self.close_session(session, counted='125', reason='Faltante documentado')
        row=reports.cash(self.period())['rows'][0]
        self.assertEqual(row[3:9],['Q100.00','Q130.00','Q125.00','Q-5.00','Q20.00','Q0.00'])

    def test_payment_statuses_and_refunds(self):
        order,_=self.consumption(8)
        card=self.payment(order,'25',method='CARD')
        payments.refund_payment(card,self.user,amount=D('25'),reason='Reembolso')
        self.payment(order,'20',method='TRANSFER')
        rejected=self.payment(order,'15',method='DEPOSIT')
        payments.reject_pending_payment(rejected,self.user,reason='No recibido')
        methods={row[0]:row for row in reports.methods(self.period())['rows']}
        self.assertEqual(methods['Tarjeta'][1:],['Q25.00','Q0.00','Q0.00','Q25.00','Q0.00'])
        self.assertEqual(methods['Transferencia'][2],'Q20.00')
        self.assertEqual(methods['Depósito'][3],'Q15.00')

    def test_all_report_pages_and_empty_hubs(self):
        self.consumption()
        for url in ['/gerencia/reportes/','/gerencia/configuracion/','/gerencia/auditoria/'] + [f'/gerencia/reportes/{kind}/' for kind in reports.REPORTS]:
            with self.subTest(url=url): self.assertEqual(self.client.get(url).status_code,200)

    def test_report_hub_groups_choices_and_contextual_help(self):
        hub = self.client.get('/gerencia/reportes/')
        self.assertEqual([group['title'] for group in hub.context['report_groups']],
            ['Ventas y operación', 'Control', 'Clientes y eventos'])
        self.assertContains(hub, 'Operación actual')
        self.assertContains(hub, 'Elige las fechas una vez')
        summary = self.client.get('/gerencia/reportes/jornada/')
        self.assertContains(summary, 'Para leer correctamente el resumen')
        self.assertContains(summary, 'Todos los reportes')
        products = self.client.get('/gerencia/reportes/productos/')
        self.assertNotContains(products, 'Los pagos por verificar ya forman parte')

    def test_explicit_permissions_even_manager(self):
        self.manager.user_permissions.clear()
        for url in ['/gerencia/reportes/','/gerencia/reportes/jornada/','/gerencia/reportes/jornada/pdf/','/gerencia/auditoria/','/gerencia/configuracion/','/gerencia/configuracion/bank/']:
            self.assertEqual(self.client.get(url).status_code,403,url)

    def test_pdf_permission_filename_pages_and_content(self):
        self.consumption()
        self.manager.user_permissions.remove(Permission.objects.get(codename='export_reports_pdf'))
        self.assertEqual(self.client.get('/gerencia/reportes/jornada/pdf/').status_code,403)
        self.manager.user_permissions.add(Permission.objects.get(codename='export_reports_pdf'))
        response=self.client.get('/gerencia/reportes/jornada/pdf/')
        self.assertEqual(response.status_code,200)
        self.assertEqual(response['Content-Type'],'application/pdf')
        self.assertIn('big-party-jornada-',response['Content-Disposition'])
        self.assertTrue(response.content.startswith(b'%PDF'))
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(response.content))
        text='\n'.join(page.extract_text() for page in reader.pages)
        for expected in ['Resumen de ventas','Julia Morales','Q100.00','Página','Productos','Cobros']:
            self.assertIn(expected,text)
        self.assertIn('no-store',response['Cache-Control'])
        self.assertGreaterEqual(len(reader.pages),1)

    def test_pdf_splits_very_long_reason_across_pages(self):
        from apps.operations.management.report_pdf import generate
        from pypdf import PdfReader
        report={'title':'Motivos extensos','kpis':[], 'sections':[{'title':'Reembolsos','columns':['Motivo','Importe'], 'rows':[['Texto largo ' * 2000,'Q25.00']]}]}
        reader=PdfReader(BytesIO(generate(report,self.period(),self.manager)))
        self.assertGreater(len(reader.pages),1)
        self.assertIn('Q25.00',''.join(p.extract_text() for p in reader.pages))

    def test_pdf_limit_is_explicit(self):
        from apps.operations.management.report_pdf import generate
        with self.assertRaises(ValidationError):
            generate({'sections':[{'rows':list(range(1001))}]},self.period(),self.manager)

    def test_business_defaults_save_and_audit(self):
        self.assertEqual(config.business().business_name,'BIG PARTY')
        self.assertEqual(config.business().timezone,'America/Guatemala')
        response=self.client.post('/gerencia/configuracion/business/',{'business_name':'BIG PARTY Centro'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(config.business().business_name,'BIG PARTY Centro')
        log=AuditLog.objects.get(action='CONFIGURATION_UPDATED')
        self.assertEqual(log.user,self.manager)
        self.assertIn(('Nombre del negocio','BIG PARTY → BIG PARTY Centro'),visible_data(log.data))

    def methods_data(self, disabled):
        data={}
        for index, code in enumerate(Payment.Method.values):
            if code not in disabled: data[code+'_enabled']='on'
            data[code+'_order']=index
        return data

    def test_disable_backend_ui_history_and_review_pending(self):
        order,_=self.consumption(8)
        historical=self.payment(order,'25',method='CARD')
        pending=self.payment(order,'20',method='TRANSFER')
        response=self.client.post('/gerencia/configuracion/methods/', self.methods_data(['CARD','TRANSFER']))
        self.assertEqual(response.status_code,302)
        for method in ['CARD','TRANSFER']:
            with self.assertRaisesMessage(ValidationError,'deshabilitado'): self.payment(order,'25',method=method)
        html=render_to_string('operations/account.html', {'payment_methods':config.enabled_methods(), 'order':order})
        self.assertNotIn('data-method="tarjeta"',html)
        self.assertNotIn('data-method="transferencia"',html)
        self.assertIn('data-method="efectivo"',html)
        payments.confirm_pending_payment(pending,self.user)
        historical.refresh_from_db();pending.refresh_from_db()
        self.assertEqual(historical.status,'CONFIRMED');self.assertEqual(pending.status,'CONFIRMED')
        self.assertIn('Q25.00',str(reports.methods(self.period())['rows']))
        self.client.post('/gerencia/configuracion/methods/', self.methods_data([]))
        self.payment(order,'25',method='CARD')

    def test_bank_validation_and_public_partial(self):
        self.assertIsNone(config.bank())
        invalid=self.client.post('/gerencia/configuracion/bank/',{'enabled':'on'})
        self.assertContains(invalid,'completa banco')
        response=self.client.post('/gerencia/configuracion/bank/', {'enabled':'on','bank_name':'Banco Demo','account_name':'Big Party Demo','account_number':'000-DEMO','instructions':'Incluir referencia'})
        self.assertEqual(response.status_code,302)
        html=render_to_string('operations/management/partials/bank_details.html',{'bank_details':config.bank()})
        for value in ['Banco Demo','Big Party Demo','000-DEMO','Incluir referencia']: self.assertIn(value,html)
        self.assertNotIn('password',html)

    def test_post_csrf_and_readonly(self):
        csrf=Client(enforce_csrf_checks=True)
        page=csrf.get('/gerencia/acceso/')
        response=csrf.post('/gerencia/acceso/',{'username':self.manager.username,'password':'Report-test-882!','csrfmiddlewaretoken':csrf.cookies['csrftoken'].value})
        self.assertEqual(response.status_code,302)
        self.assertEqual(csrf.post('/gerencia/configuracion/business/',{'business_name':'Ataque'}).status_code,403)
        self.assertEqual(self.client.post('/gerencia/auditoria/').status_code,405)
        self.assertFalse(BusinessSettings.objects.exists())

    def test_configuration_links_respect_permissions(self):
        response=self.client.get('/gerencia/configuracion/')
        for link in ['/gerencia/reservas/configuracion/','/gerencia/eventos/configuracion/','/impresoras/','/gerencia/usuarios/']:
            self.assertContains(response,link)
        self.manager.user_permissions.remove(Permission.objects.get(codename='change_event'))
        self.assertNotContains(self.client.get('/gerencia/configuracion/'),'/gerencia/eventos/configuracion/')

    def test_audit_system_actor_without_user(self):
        log=AuditLog.objects.create(action='events.purchase_created',entity='events.EventPurchase',entity_id='1')
        self.assertContains(self.client.get('/gerencia/auditoria/'),'Sistema')
        self.assertContains(self.client.get(f'/gerencia/auditoria/{log.pk}/'),'Sistema')

    def test_audit_filters_detail_pagination_and_secret_projection(self):
        dangerous={'password':'PASSWORD-CONTENT','PIN':'9841','hash':'HASH-CONTENT','qr_token':'QR-CONTENT','secure_token':'SECURE-CONTENT',
                   'session_key':'SESSION-CONTENT','reason':{'password':'NESTED-CONTENT'}, 'old_price':'25','new_price':'30',
                   'changes':{'business_name':{'before':{'password':'DEEP'},'after':'SAFE'},'password':{'before':'A','after':'B'}}}
        log=AuditLog.objects.create(user=self.manager, action='catalog.price_changed', entity='catalog.product', entity_id='2', data=dangerous)
        detail=self.client.get(f'/gerencia/auditoria/{log.pk}/')
        self.assertContains(detail,'Cambió un precio');self.assertContains(detail,'25');self.assertContains(detail,'30')
        for secret in ['PASSWORD-CONTENT','9841','HASH-CONTENT','QR-CONTENT','SECURE-CONTENT','SESSION-CONTENT','NESTED-CONTENT','DEEP','qr_token','secure_token','password','PIN']:
            self.assertNotContains(detail,secret)
        self.assertEqual(self.client.post(f'/gerencia/auditoria/{log.pk}/').status_code,405)
        for params in [{'user':'Julia'},{'module':'Inventario'},{'action':'price_changed'},{'q':'#2'}]:
            self.assertContains(self.client.get('/gerencia/auditoria/',params),'Cambió un precio')
        self.assertNotContains(self.client.get('/gerencia/auditoria/',{'module':'Caja'}),'Cambió un precio</strong>')
        for n in range(30): AuditLog.objects.create(user=self.manager,action='catalog.price_changed',entity='catalog.product',entity_id=str(n))
        response=self.client.get('/gerencia/auditoria/',{'page':2,'user':'Julia','module':'Inventario'})
        self.assertEqual(response.context['rows'].number,2)
        self.assertEqual(response.context['rows'].paginator.count,31)
        self.assertLessEqual(len(response.context['entries']),25)
        self.manager.user_permissions.remove(Permission.objects.get(codename='view_audit_log'))
        self.assertEqual(self.client.get(f'/gerencia/auditoria/{log.pk}/').status_code,403)

from apps.reservations.tests.base import ReservationCase
from apps.events.tests.base import EventCase


class ReservationReportTests(ReservationCase):
    def period(self):
        day=self.start.date()
        return reports.Period({'period':'day','start':day,'end':day})

    def test_statuses_and_credit_fee_are_separate(self):
        self.confirmed(paid=True, application='CREDIT')
        from apps.tables.models import VenueTable
        self.table=VenueTable.objects.create(area=self.area,name='VIP 3',capacity=6,reservable_web=True)
        self.confirmed(paid=True,application='FEE')
        rows=reports.reservations(self.period())
        statuses=dict(rows[0]['rows'])
        self.assertEqual(statuses['Solicitudes totales'],2)
        self.assertEqual(statuses['Confirmada'],2)
        self.assertEqual(rows[1]['rows'],[['Abono al consumo','Q300.00'],['Cargo de reserva','Q300.00']])
        self.assertEqual(reports.commercial_totals(self.period())['confirmed'],D('0'))

    def test_only_allocated_credit_reduces_consumption_balance(self):
        from apps.cash.services import open_business_day
        from apps.reservations.services import confirm_reservation_arrival
        from apps.catalog.models import Category, Product
        from apps.payments.queries import get_financial_summary
        open_business_day(self.admin)
        row=self.confirmed(paid=True)
        row=confirm_reservation_arrival(row,self.manager,self.waiter)
        period=reports.Period({'period':'current'})
        self.assertEqual(reports.commercial_totals(period)['credit'],D('0'))
        self.assertEqual(reports.commercial_totals(period)['balance'],D('0'))
        category=Category.objects.create(name='Bebidas',slug='bebidas')
        product=Product.objects.create(name='Bebida',slug='bebida',category=category,base_price=100)
        orders.add_product_to_order(row.order,product,1,self.admin)
        orders.send_order(row.order,self.admin)
        totals=reports.commercial_totals(period)
        self.assertEqual(totals['credit'],D('100'))
        self.assertEqual(totals['confirmed'],D('0'))
        self.assertEqual(totals['balance'],get_financial_summary(row.order)['outstanding_balance'])

    def test_reservation_page_bank_and_missing_configuration(self):
        from django.urls import reverse
        row=self.approve(paid=True)
        url=reverse('reservation-client:detail',args=[row.secure_token])
        self.assertContains(self.client.get(url),'Gerencia debe completar')
        BankTransferSettings.objects.create(enabled=True,bank_name='Banco Demo',account_name='Big Party Demo',account_number='000-DEMO')
        self.assertContains(self.client.get(url),'000-DEMO')


class EventReportTests(EventCase):
    def period(self):
        day=timezone.localtime(self.event.starts_at).date()
        return reports.Period({'period':'day','start':day,'end':day})

    def test_event_confirmed_only_courtesy_and_table_access(self):
        from apps.events import services as events
        from apps.events.models import EventTicket
        self.confirm()
        table=self.buy(table=True);self.confirm(table)
        events.issue_courtesy_tickets(self.event,self.courtesy,2,self.manager,reason='Invitados')
        self.submit(self.buy({self.general.pk:1}))
        ticket=EventTicket.objects.filter(event=self.event).first()
        events.validate_and_use_ticket(ticket.qr_token,self.guard)
        row=reports.events(self.period())['rows'][0]
        self.assertEqual(row[3:],[2,2,6,1,'Q800.00','Q100.00'])
        self.assertEqual(reports.commercial_totals(self.period())['confirmed'],D('0'))

    def test_event_portal_displays_configured_bank(self):
        from django.urls import reverse
        purchase=self.buy()
        url=reverse('event-public:portal',args=[purchase.secure_token])
        self.assertContains(self.client.get(url),'Gerencia debe completar')
        BankTransferSettings.objects.create(enabled=True,bank_name='Banco Demo',account_name='Big Party Demo',account_number='000-DEMO')
        self.assertContains(self.client.get(url),'000-DEMO')
