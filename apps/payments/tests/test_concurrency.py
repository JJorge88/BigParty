from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase

from apps.cash.services import open_business_day
from apps.catalog.models import Category, Product
from apps.inventory.models import InventoryMovement
from apps.orders import services as orders
from apps.payments import services as s
from apps.payments.models import Payment, PaymentAllocation, PaymentRefund
from apps.tables.models import VenueTable
from apps.venues.models import Area


class PaymentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="payment-concurrent")
        self.day = open_business_day(self.user)
        area = Area.objects.create(name="Área", slug="area")
        table = VenueTable.objects.create(area=area, name="Mesa", capacity=4)
        category = Category.objects.create(name="Productos", slug="productos")
        self.product = Product.objects.create(category=category, name="Gallo", slug="gallo", base_price=25,
                                              track_inventory=True, stock_quantity=10)
        self.order = orders.open_table_order(table, self.user)
        self.line = orders.add_product_to_order(self.order, self.product, 2, self.user)
        orders.send_order(self.order, self.user)

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

    def test_two_full_payments_only_one_succeeds(self):
        operation = lambda user: s.pay_full_balance(self.order, "CASH", user)
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(PaymentAllocation.objects.count(), 2)
        self.assertEqual(s.get_order_balance(self.order), D("0"))

    def test_selected_double_payment_cannot_overassign_units(self):
        operation = lambda user: s.create_selected_payment(self.order, [{"line_id": self.line.pk, "quantity": 2}], "CASH", user)
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(PaymentAllocation.objects.count(), 2)
        self.assertEqual(s.get_line_payment_quantities(self.line)["confirmed_quantity"], 2)

    def test_concurrent_partial_payments_apply_to_distinct_units(self):
        operation = lambda user: s.create_amount_payment(self.order, D("25"), "CASH", user)
        self.assertEqual(self.run_concurrent([operation, operation]), [True, True])
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(set(PaymentAllocation.objects.values_list("unit_number", flat=True)), {1, 2})
        self.assertEqual(s.get_order_balance(self.order), D("0"))

    def test_pending_and_cash_cannot_cover_same_balance(self):
        operations = [lambda user: s.pay_full_balance(self.order, "TRANSFER", user, reference="R"),
                      lambda user: s.pay_full_balance(self.order, "CASH", user)]
        self.assertCountEqual(self.run_concurrent(operations), [True, False])
        self.assertEqual(Payment.objects.count(), 1)
        summary = s.get_financial_summary(self.order)
        self.assertEqual(summary["confirmed_paid"] + summary["pending_verification"], D("50"))

    def test_confirm_and_reject_serialize_one_transition(self):
        payment = s.pay_full_balance(self.order, "TRANSFER", self.user, reference="R")
        operations = [lambda user: s.confirm_pending_payment(payment, user),
                      lambda user: s.reject_pending_payment(payment, user, "No recibido")]
        self.assertCountEqual(self.run_concurrent(operations), [True, False])
        self.assertEqual(self.order.activities.filter(activity_type__in=["PAYMENT_CONFIRMED", "PAYMENT_REJECTED"]).count(), 1)

    def test_two_refunds_return_money_and_stock_once(self):
        from apps.cash.models import CashRegister
        from apps.cash.services import open_cash_session
        register = CashRegister.objects.create(name="Caja", code="TEST", area=self.order.area)
        session = open_cash_session(register, self.user, 0, self.user)
        payment = s.pay_full_balance(self.order, "CASH", self.user, cash_session=session)
        allocation = payment.allocations.order_by("pk").first()
        operation = lambda user: s.refund_payment(payment, user, allocation_ids=[allocation.pk], return_to_inventory=True, reason="Devuelto")
        self.assertCountEqual(self.run_concurrent([operation, operation]), [True, False])
        self.assertEqual(PaymentRefund.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 9)
        self.assertEqual(InventoryMovement.objects.filter(movement_type="REFUND_RETURN").count(), 1)

    def test_payment_and_cancellation_cannot_both_change_same_consumption(self):
        operations = [lambda user: s.pay_full_balance(self.order, "CASH", user),
                      lambda user: orders.cancel_sent_line(self.line, user, "Error")]
        self.assertCountEqual(self.run_concurrent(operations), [True, False])
        self.line.refresh_from_db()
        self.assertEqual(Payment.objects.exists(), self.line.status == "SENT")

    def test_discount_and_payment_cannot_overcover_same_balance(self):
        operations = [lambda user: s.create_amount_payment(self.order, D("50"), "CASH", user),
                      lambda user: s.apply_order_adjustment(self.order, user, amount=D("50"), reason="Cortesía")]
        self.assertCountEqual(self.run_concurrent(operations), [True, False])
        self.assertEqual(s.get_order_balance(self.order), D("0"))
