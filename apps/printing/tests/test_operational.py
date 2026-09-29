from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client

from apps.cash.tests.base import CashTestCase
from apps.operations.tests import test_cash_sales as sales_tests
from apps.operations.tests.base import OperationsTestCase
from apps.orders import services as orders
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.printing import services
from apps.printing.models import Printer, PrintJob
from apps.printing.views import token


class CashPrintingTests(CashTestCase):
    setUp = sales_tests.CashSalesTests.setUp
    create_sale = sales_tests.CashSalesTests.create_sale
    post = sales_tests.CashSalesTests.post
    state = sales_tests.CashSalesTests.state
    add = sales_tests.CashSalesTests.add
    quote = sales_tests.CashSalesTests.quote
    pay = sales_tests.CashSalesTests.pay
    revoke = sales_tests.CashSalesTests.revoke

    def printers(self):
        self.bar=Printer.objects.create(name='Barra 1',code='BAR',printer_type='BAR',area=self.area)
        self.kitchen=Printer.objects.create(name='Cocina',code='KITCHEN',printer_type='KITCHEN')

    def allow_printing(self):
        self.cashier.user_permissions.add(*Permission.objects.filter(content_type__app_label='printing').exclude(codename__in=['manage_printers','test_printer']))
        self.cashier=type(self.cashier).objects.get(pk=self.cashier.pk)

    def test_quick_only_kitchen_after_completed_payment(self):
        self.printers(); order=self.create_sale(); self.add(order,quantity=2); self.add(order,self.food)
        self.post(order,'cobrar',alias='Juan')
        self.assertEqual(self.pay(order,method='transferencia').status_code,200)
        self.assertFalse(PrintJob.objects.exists())
        payments.confirm_pending_payment(order.payments.get(),self.user)
        self.assertFalse(PrintJob.objects.exists())
        payments.close_order(order,self.cashier)
        job=order.print_jobs.get(); self.assertEqual(job.printer,self.kitchen)
        text=job.payload_snapshot['text']
        self.assertIn('Juan',text); self.assertIn('Caja SPORT',text)
        self.assertNotIn('MESA',text); self.assertNotIn('CERVEZA',text)

    def test_no_alias_line_if_blank(self):
        self.printers(); order=self.create_sale(); self.add(order,self.food); self.pay(order)
        self.assertNotIn('ALIAS:',order.print_jobs.get().payload_snapshot['text'])

    def test_alias_visibility_follows_kitchen_components(self):
        order=self.create_sale(); state=self.add(order)
        self.assertFalse(state['has_kitchen'])
        state=self.add(order,self.food); self.assertTrue(state['has_kitchen'])
        self.post(order,'cobrar',alias='No borrar')
        line=order.lines.get(product=self.food)
        state=self.post(order,'eliminar',line=line.pk).json()['state']
        self.assertFalse(state['has_kitchen']); self.assertEqual(state['customer_alias'],'No borrar')
        self.assertContains(self.client.get(f'/caja/orden/{order.pk}/pedido/'),'id="customer-alias-field" hidden')

    def test_rejected_transfer_and_deposit_release_stock_idempotently(self):
        for method in ['transferencia','deposito']:
            order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method=method)
            self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,98)
            payment=order.payments.get(); payments.reject_pending_payment(payment,self.user,'No ingresó')
            self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
            order.refresh_from_db(); self.assertIsNotNone(order.reservation_released_at)
            orders.release_quick_sale_stock(order,self.user,'Revisión')
            self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
            self.assertFalse(order.print_jobs.exists())

    def test_continuing_rejected_sale_reacquires_stock_once(self):
        self.printers(); order=self.create_sale(); self.add(order,quantity=2); self.add(order,self.food)
        self.pay(order,method='transferencia'); payments.reject_pending_payment(order.payments.get(),self.user,'Rechazado')
        self.assertEqual(self.pay(order).status_code,200)
        order.refresh_from_db(); self.product.refresh_from_db(); self.food.refresh_from_db()
        self.assertEqual(order.status,'CLOSED'); self.assertIsNone(order.reservation_released_at)
        self.assertEqual(self.product.stock_quantity,98); self.assertEqual(self.food.stock_quantity,19)
        self.assertEqual(order.print_jobs.count(),1)

    def test_insufficient_stock_blocks_new_payment_after_release(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method='transferencia')
        payments.reject_pending_payment(order.payments.get(),self.user,'No ingresó')
        self.product.stock_quantity=1; self.product.save()
        response=self.pay(order)
        self.assertEqual(response.status_code,409)
        self.assertEqual(order.payments.count(),1); self.assertFalse(order.tickets.exists())
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,1)

    def test_direct_payment_service_also_revalidates_released_stock(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method='transferencia')
        payments.reject_pending_payment(order.payments.get(),self.user,'No ingresó')
        self.product.stock_quantity=0; self.product.save()
        with self.assertRaises(ValidationError): payments.pay_full_balance(order,'CARD',self.cashier,card_approved=True)
        self.assertEqual(order.payments.count(),1)

    def test_explicit_cancel_draft_and_rejected_sale(self):
        for rejected in [False,True]:
            order=self.create_sale(); self.add(order,quantity=2)
            if rejected:
                self.pay(order,method='transferencia'); payments.reject_pending_payment(order.payments.get(),self.user,'No ingresó')
            response=self.client.post(f'/caja/orden/{order.pk}/anular/',{'reason':'Cliente se retiró'},HTTP_ACCEPT="application/json" if rejected else "text/html")
            self.assertEqual(response.status_code,200 if rejected else 302)
            if rejected: self.assertEqual(response.json()["next"],"/caja/venta-rapida/")
            order.refresh_from_db(); self.assertEqual(order.status,'CANCELLED')
            self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
            self.assertFalse(order.lines.exclude(status='CANCELLED').exists())
            payments._assert_ledger(order)

    def test_cancel_with_partial_payment_keeps_financial_history_and_releases(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,amount='25')
        result=orders.cancel_quick_sale(order,self.cashier,'Cliente se retiró')
        self.assertNotEqual(result.status,'CANCELLED')
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        self.assertEqual(order.payments.get().status,'CONFIRMED'); self.assertFalse(order.tickets.exists())
        self.assertEqual(self.pay(order).status_code,200)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,98)

    def test_cancel_pending_confirmation_reacquires_before_approval(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method='transferencia')
        orders.cancel_quick_sale(order,self.cashier,'Cliente se retiró')
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        payments.confirm_pending_payment(order.payments.get(),self.user)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,98)

    def test_cancel_pending_confirmation_fails_if_stock_unavailable(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method='transferencia')
        orders.cancel_quick_sale(order,self.cashier,'Cliente se retiró')
        self.product.stock_quantity=0; self.product.save()
        with self.assertRaises(ValidationError): payments.confirm_pending_payment(order.payments.get(),self.user)
        self.assertEqual(order.payments.get().status,'PENDING')

    def test_cancel_requires_reason_permission_and_cannot_cancel_fulfilled(self):
        order=self.create_sale(); self.add(order)
        self.assertEqual(self.client.post(f'/caja/orden/{order.pk}/anular/',{'reason':''}).status_code,409)
        self.revoke('cancel_quick_sale')
        self.assertEqual(self.client.post(f'/caja/orden/{order.pk}/anular/',{'reason':'Error'}).status_code,403)
        self.pay(order)
        with self.assertRaises(ValidationError): orders.release_quick_sale_stock(order,self.user,'No')

    def test_receipt_button_permission_and_explicit_post(self):
        self.printers(); self.allow_printing(); order=self.create_sale(); self.add(order); self.pay(order)
        self.assertFalse(order.print_jobs.exists())
        self.assertContains(self.client.get(f'/caja/orden/{order.pk}/completada/'),'Imprimir recibo')
        page=self.client.get(f'/caja/orden/{order.pk}/recibo/')
        self.assertEqual(page.status_code,200); self.assertFalse(order.print_jobs.exists())
        response=self.client.post(f'/caja/orden/{order.pk}/recibo/',{'token':page.context['token']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(order.print_jobs.get().printer,self.bar)
        self.assertEqual(order.print_jobs.get().job_type,'RECEIPT')

    def test_receipt_rejects_forged_token_and_wrong_area(self):
        self.printers(); self.allow_printing(); order=self.create_sale(); self.add(order); self.pay(order)
        url=f'/caja/orden/{order.pk}/recibo/'
        self.assertEqual(self.client.post(url,{'token':'fake'}).status_code,409)
        self.assertEqual(self.client.post(url,{'token':token(self.user,'receipt',order.pk)}).status_code,409)
        other=self.open(self.destination); other.area=self.other_area; other.save()
        self.assertEqual(self.client.get(f'/caja/orden/{other.pk}/recibo/').status_code,404)
        self.assertFalse(order.print_jobs.exists())

    def test_receipt_csrf_post_required(self):
        self.allow_printing(); order=self.create_sale(); self.add(order); self.pay(order)
        client=Client(enforce_csrf_checks=True); client.cookies.update(self.client.cookies)
        self.assertEqual(client.post(f'/caja/orden/{order.pk}/recibo/',{'token':token(self.cashier,'receipt',order.pk)}).status_code,403)
        self.assertFalse(order.print_jobs.exists())

    def test_cash_history_permissions_scope_and_retry(self):
        order=self.open(); orders.add_product_to_order(order,self.product,1,self.user); orders.send_order(order,self.user)
        self.assertEqual(self.client.get('/caja/impresiones/').status_code,403)
        self.allow_printing(); job=order.print_jobs.get()
        self.assertContains(self.client.get('/caja/impresiones/'),str(job.pk))
        self.printers()
        self.assertEqual(self.client.get(f'/caja/impresiones/{job.pk}/retry/').status_code,405)
        self.assertEqual(self.client.post(f'/caja/impresiones/{job.pk}/retry/').status_code,302)
        job.refresh_from_db(); self.assertEqual(job.status,'PENDING')
        other=self.open(self.destination)
        other.area=self.other_area; other.save()
        orders.add_product_to_order(other,self.product,1,self.user); orders.send_order(other,self.user)
        foreign=other.print_jobs.get()
        self.assertEqual(self.client.post(f'/caja/impresiones/{foreign.pk}/retry/').status_code,403)

    def test_completed_sale_shows_accepted_but_failed_print_notice(self):
        order=self.create_sale(); self.add(order,self.food); self.pay(order)
        page=self.client.get(f'/caja/orden/{order.pk}/completada/')
        self.assertContains(page,'Venta completada'); self.assertContains(page,'Pedido registrado. No se pudo imprimir en Cocina.')

    def test_refund_of_unfulfilled_sale_releases_stock_without_double_return(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,amount='25')
        payment=order.payments.get()
        payments.refund_payment(payment,self.user,reason='Cliente se retiró',allocation_ids=list(payment.allocations.values_list('pk',flat=True)),return_to_inventory=True)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        orders.cancel_quick_sale(order,self.cashier,'Reembolsada')
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        order.refresh_from_db(); self.assertEqual(order.status,'CANCELLED')
        payments._assert_ledger(order)

    def test_partial_refund_blocks_fulfillment_but_keeps_stock_free(self):
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,amount='25')
        payments.refund_payment(order.payments.get(),self.user,amount='10',reason='Resolución')
        with self.assertRaises(ValidationError): orders.reserve_quick_sale_stock(order,self.cashier)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)
        self.assertFalse(order.tickets.exists())

    def test_count_requires_explicit_release_of_unfinished_reservations(self):
        from apps.cash import services as cash
        order=self.create_sale(); self.add(order,quantity=2); self.pay(order,method='transferencia')
        with self.assertRaises(ValidationError): cash.submit_blind_cash_count(self.cash_session,'500',self.cashier)
        orders.cancel_quick_sale(order,self.cashier,'Inconclusa al cierre')
        cash.submit_blind_cash_count(self.cash_session,'500',self.cashier)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,100)


class WaiterPrintingTests(OperationsTestCase):
    def test_waiter_closed_receipt_permission_scope_and_close_button(self):
        self.waiter.user_permissions.add(*Permission.objects.filter(codename__in=['record_payment','close_order','print_customer_receipt']))
        order=self.open(); orders.add_product_to_order(order,self.product,1,self.user); orders.send_order(order,self.user)
        payments.pay_full_balance(order,'CARD',self.user,card_approved=True)
        self.enter()
        result=self.client.post(f'/operacion/orden/{order.pk}/cuenta/cerrar/',HTTP_ACCEPT='application/json')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['receipt_url'],f'/operacion/orden/{order.pk}/recibo/')
        page=self.client.get(result.json()['receipt_url']); self.assertEqual(page.status_code,200)
        self.assertFalse(order.print_jobs.filter(job_type='RECEIPT').exists())
        self.assertEqual(self.client.post(result.json()['receipt_url'],{'token':page.context['token']}).status_code,302)
        self.assertEqual(order.print_jobs.filter(job_type='RECEIPT').count(),1)

    def test_normal_waiter_cannot_use_technical_or_receipt_actions(self):
        order=self.open(); self.enter()
        self.assertEqual(self.client.get(f'/operacion/orden/{order.pk}/recibo/').status_code,403)
        self.assertEqual(self.client.get('/impresoras/').status_code,302)
        self.assertEqual(self.client.get('/caja/impresiones/').status_code,302)
