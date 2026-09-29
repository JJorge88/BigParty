from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase
from django.utils import timezone
from apps.cash.services import open_business_day
from apps.orders.models import TableOrder
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.reservations import services as s
from apps.reservations.models import Reservation


class ReservationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_superuser(username='concurrent-reservation',role='MESERO')
        area=Area.objects.create(name='VIP',slug='vip')
        self.table=VenueTable.objects.create(area=area,name='VIP 2',capacity=6,reservable_web=True)
        self.start=timezone.localtime(timezone.now()+timedelta(days=1))

    def request(self):
        return s.create_public_reservation_request(self.table,'Ana','+50255555555',self.start.date(),self.start.time().replace(tzinfo=None),4)

    def run_two(self, operations):
        barrier=Barrier(2)
        def worker(operation):
            try:
                barrier.wait(timeout=10)
                try:
                    operation()
                    return True
                except ValidationError:
                    return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(worker,op) for op in operations]
            return [future.result(timeout=30) for future in futures]

    def test_simultaneous_requests_only_one_hold(self):
        self.assertCountEqual(self.run_two([self.request,self.request]),[True,False])
        self.assertEqual(Reservation.objects.count(),1)

    def test_simultaneous_arrivals_only_one_order(self):
        row=s.approve_reservation(self.request(),self.user,payment_required=False)
        open_business_day(self.user)
        operation=lambda:s.confirm_reservation_arrival(row,self.user,self.user)
        self.assertCountEqual(self.run_two([operation,operation]),[True,False])
        self.assertEqual(TableOrder.objects.count(),1)

    def test_approval_and_rejection_only_one_decision(self):
        row=self.request()
        self.assertCountEqual(self.run_two([lambda:s.approve_reservation(row,self.user,payment_required=False),
                                           lambda:s.reject_reservation(row,self.user,'No disponible')]),[True,False])

    def test_manual_and_public_request_cannot_overlap(self):
        manual=lambda:s.create_manual_reservation(self.table,'Ana','+50255555555',self.start.date(),
                    self.start.time().replace(tzinfo=None),4,self.user,payment_required=False)
        self.assertCountEqual(self.run_two([manual,self.request]),[True,False])
        self.assertEqual(Reservation.objects.count(),1)

    def test_two_submissions_and_payment_decisions_are_serialized(self):
        row=s.create_manual_reservation(self.table,'Ana','+50255555555',self.start.date(),
                    self.start.time().replace(tzinfo=None),4,self.user,payment_required=True,payment_value=300)
        submit=lambda:s.submit_reservation_payment(row,300,'TEST')
        self.assertCountEqual(self.run_two([submit,submit]),[True,False])
        payment=row.payment
        self.assertCountEqual(self.run_two([lambda:s.confirm_reservation_payment(payment,self.user),
                                           lambda:s.reject_reservation_payment(payment,self.user,'No recibido')]),[True,False])
