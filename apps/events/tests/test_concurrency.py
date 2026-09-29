from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase
from apps.events import services as s, queries as q
from apps.events.models import Event, EventTicket
from .base import Fixtures


class ConcurrencyTests(Fixtures, TransactionTestCase):
    def run_two(self, operations):
        barrier=Barrier(2)
        def worker(operation):
            try:
                barrier.wait(timeout=10)
                try:return operation()
                except ValidationError:return 'blocked'
            finally:connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,operation) for operation in operations]
            return [f.result(timeout=30) for f in futures]

    def test_last_individual_quota(self):
        s.save_ticket_type(self.event,self.manager,self.general,capacity=2)
        result=self.run_two([self.buy,self.buy])
        self.assertEqual(result.count('blocked'),1);self.assertEqual(q.type_committed(self.general),2)

    def test_last_table(self):
        operation=lambda:self.buy(table=True)
        result=self.run_two([operation,operation])
        self.assertEqual(result.count('blocked'),1);self.assertEqual(q.get_event_capacity_summary(self.event)['held'],6)

    def test_global_limit_even_if_configuration_was_corrupted(self):
        # Simula datos heredados fuera del servicio: el guard de aforo sigue siendo absoluto.
        Event.objects.filter(pk=self.event.pk).update(maximum_capacity=3)
        result=self.run_two([self.buy,lambda:self.buy({self.vip.pk:2})])
        self.assertEqual(result.count('blocked'),1)
        self.event.refresh_from_db();self.assertEqual(q.get_event_capacity_summary(self.event)['remaining'],1)

    def test_double_confirmation_returns_same_tickets(self):
        payment=self.submit()
        operation=lambda:[t.pk for t in s.confirm_event_payment(payment,self.manager)]
        result=self.run_two([operation,operation])
        self.assertEqual(result[0],result[1]);self.assertEqual(EventTicket.objects.count(),2)

    def test_concurrent_ticket_generation_idempotent(self):
        tickets=self.confirm();purchase=tickets[0].purchase
        operation=lambda:[t.pk for t in s.generate_purchase_tickets(purchase,self.manager)]
        result=self.run_two([operation,operation])
        self.assertEqual(result[0],result[1]);self.assertEqual(EventTicket.objects.count(),2)

    def test_two_different_guards_same_qr(self):
        from django.contrib.auth import get_user_model
        second=get_user_model().objects.create_user(username='guard-two',role='GUARDIA')
        second.user_permissions.set(self.guard.user_permissions.all())
        ticket=self.confirm()[0]
        results=self.run_two([lambda:s.validate_and_use_ticket(ticket.qr_token,self.guard)['result'],lambda:s.validate_and_use_ticket(ticket.qr_token,second)['result']])
        self.assertCountEqual(results,['VALID','USED'])
        self.assertEqual(EventTicket.objects.filter(status='USED').count(),1)

    def test_scan_and_cancel_serialized_final_cancelled(self):
        ticket=self.confirm()[0]
        self.run_two([lambda:s.validate_and_use_ticket(ticket.qr_token,self.guard),lambda:s.cancel_event(self.event,self.manager,'Suspensión')])
        ticket.refresh_from_db();self.assertEqual(ticket.status,'CANCELLED')

    def test_confirm_reject_race_single_decision(self):
        payment=self.submit()
        result=self.run_two([lambda:s.confirm_event_payment(payment,self.manager),lambda:s.reject_event_payment(payment,self.manager,'No recibido')])
        self.assertEqual(result.count('blocked'),1)
        payment.refresh_from_db();self.assertIn(payment.status,['CONFIRMED','REJECTED'])
        self.assertEqual(EventTicket.objects.count(),2 if payment.status=='CONFIRMED' else 0)
