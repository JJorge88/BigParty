from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal as D
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase

from apps.cash import services as s
from apps.cash.models import CashRegister, CashSession, CashMovement, BusinessDay
from apps.orders import services as orders
from apps.catalog.models import Category, Product
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.payments import services as payments


class CashConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="cash-concurrent")
        self.day = s.open_business_day(self.user)
        self.area = Area.objects.create(name="Sport Bar", slug="sport-bar")
        self.register = CashRegister.objects.create(name="Caja Sport", code="SPORT", area=self.area)
        self.table = VenueTable.objects.create(name="Mesa", area=self.area, capacity=4)
        category = Category.objects.create(name="Productos", slug="productos")
        self.product = Product.objects.create(name="Gallo", slug="gallo", category=category, base_price=25)

    def run_concurrent(self, operations):
        barrier = Barrier(2)
        def worker(operation):
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=5)
                try:
                    operation(user)
                    return True
                except ValidationError:
                    return False
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def session(self):
        return s.open_cash_session(self.register, self.user, D("100"), self.user)

    def payment(self, session=None):
        order = orders.open_table_order(self.table, self.user)
        orders.add_product_to_order(order, self.product, 1, self.user)
        orders.send_order(order, self.user)
        return payments.pay_full_balance(order, "CASH", self.user, cash_session=session)

    def test_two_session_openings_only_one_succeeds(self):
        operation = lambda user: s.open_cash_session(self.register, user, D("100"), user)
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(CashSession.objects.count(), 1)

    def test_concurrent_day_openings_create_only_one(self):
        s.close_business_day(self.day, self.user)
        operations = [lambda user, n=n: s.open_business_day(user, self.day.business_date + timedelta(days=n)) for n in (1, 2)]
        self.assertCountEqual(self.run_concurrent(operations), [True, False])
        self.assertEqual(BusinessDay.objects.filter(status="OPEN").count(), 1)

    def test_double_handoff_receives_money_once(self):
        session = self.session()
        payment = self.payment()
        operation = lambda user: s.confirm_cash_handoff(payment, session, user)
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(CashMovement.objects.filter(movement_type="WAITER_HANDOFF").count(), 1)
        self.assertEqual(s.get_expected_cash(session), D("125"))

    def test_concurrent_withdrawals_cannot_make_expected_negative(self):
        session = self.session()
        operation = lambda user: s.create_cash_withdrawal(session, D("80"), "Bóveda", user, user)
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(s.get_expected_cash(session), D("20"))

    def test_double_count_keeps_first_and_double_close_closes_once(self):
        session = self.session()
        count = lambda user: s.submit_blind_cash_count(session, D("100"), user)
        self.assertCountEqual(self.run_concurrent([count, count]), [True, False])
        close = lambda user: s.close_cash_session(session, user)
        self.assertCountEqual(self.run_concurrent([close, close]), [True, False])
        session.refresh_from_db()
        self.assertEqual(session.status, "CLOSED")

    def test_count_and_handoff_have_a_consistent_snapshot(self):
        session = self.session()
        payment = self.payment()
        results = self.run_concurrent([lambda user: s.submit_blind_cash_count(session, D("100"), user),
                                       lambda user: s.confirm_cash_handoff(payment, session, user)])
        self.assertTrue(results[0])
        session.refresh_from_db()
        self.assertEqual(session.expected_cash_at_close, s.get_expected_cash(session))
        self.assertEqual(session.expected_cash_at_close, D("125") if results[1] else D("100"))

    def test_day_close_and_new_order_cannot_both_succeed(self):
        results = self.run_concurrent([lambda user: s.close_business_day(self.day, user),
                                       lambda user: orders.open_table_order(self.table, user)])
        self.assertCountEqual(results, [True, False])
        self.day.refresh_from_db()
        self.assertEqual(self.day.orders.exists(), self.day.status == "OPEN")

    def test_legacy_close_and_new_session_leave_an_open_period(self):
        results = self.run_concurrent([lambda user: s.close_business_day(self.day, user),
                                       lambda user: s.open_cash_session(self.register, user, 0, user)])
        self.assertTrue(results[1])
        self.assertEqual(CashSession.objects.filter(status="OPEN", business_day__status="CLOSED").count(), 0)
        self.assertEqual(BusinessDay.objects.filter(status="OPEN").count(), 1)

    def test_simultaneous_first_openings_share_one_automatic_period(self):
        self.day.delete()
        other = CashRegister.objects.create(name="Other", code="OTHER", area=self.area)
        results = self.run_concurrent([
            lambda user: s.open_cash_session(self.register, user, 0, user),
            lambda user: s.open_cash_session(other, user, 0, user),
        ])
        self.assertEqual(results, [True, True])
        self.assertEqual(BusinessDay.objects.count(), 1)
        self.assertEqual(CashSession.objects.filter(status="OPEN").count(), 2)

    def test_direct_movement_retries_return_same_record(self):
        session = self.session()
        payment = self.payment(session)
        operation = lambda user: s.record_direct_cash_payment(payment, session, user)
        self.assertEqual(self.run_concurrent([operation, operation]), [True, True])
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_refund_movement_retries_do_not_duplicate_outflow(self):
        session = self.session()
        payment = self.payment(session)
        refund = payments.refund_payment(payment, self.user, amount=D("10"), reason="Devolución")
        operation = lambda user: s.record_cash_refund(refund, session, user)
        self.assertEqual(self.run_concurrent([operation, operation]), [True, True])
        self.assertEqual(CashMovement.objects.filter(movement_type="CASH_REFUND").count(), 1)
        self.assertEqual(s.get_expected_cash(session), D("115"))
