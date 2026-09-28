from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase

from apps.cash.services import open_business_day
from apps.catalog.models import Category, Product
from apps.inventory.models import InventoryMovement
from apps.orders import services as s
from apps.orders.models import TableOrder
from apps.tables.models import VenueTable
from apps.venues.models import Area


class OrderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="concurrent-orders")
        self.day = open_business_day(self.user)
        area = Area.objects.create(name="Área", slug="area")
        self.tables = [VenueTable.objects.create(area=area, name=f"Mesa {n}", capacity=4) for n in (1, 2)]
        category = Category.objects.create(name="Productos", slug="productos")
        self.product = Product.objects.create(category=category, name="Última", slug="ultima", track_inventory=True, stock_quantity=1, preparation_route="AREA_BAR")

    def concurrent(self, operations):
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

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker, operation) for operation in operations]
            return [future.result(timeout=15) for future in futures]

    def test_two_openings_of_same_table_create_one_order(self):
        operation = lambda user: s.open_table_order(self.tables[0], user)
        self.assertCountEqual(self.concurrent([operation, operation]), [True, False])
        self.assertEqual(TableOrder.objects.count(), 1)

    def test_two_orders_compete_for_last_stock_atomically(self):
        orders = [s.open_table_order(table, self.user) for table in self.tables]
        for order in orders:
            s.add_product_to_order(order, self.product, 1, self.user)
        operations = [lambda user, order=order: s.send_order(order, user) for order in orders]
        self.assertCountEqual(self.concurrent(operations), [True, False])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 0)
        self.assertEqual(InventoryMovement.objects.count(), 1)

    def test_double_send_same_order_does_not_double_consume(self):
        order = s.open_table_order(self.tables[0], self.user)
        s.add_product_to_order(order, self.product, 1, self.user)
        operation = lambda user: s.send_order(order, user)
        self.assertEqual(self.concurrent([operation, operation]), [True, True])
        self.assertEqual(InventoryMovement.objects.count(), 1)
        self.assertEqual(order.tickets.count(), 1)

    def test_concurrent_additions_group_without_losing_quantity(self):
        order = s.open_table_order(self.tables[0], self.user)
        operation = lambda user: s.add_product_to_order(order, self.product, 1, user)
        self.assertEqual(self.concurrent([operation, operation]), [True, True])
        self.assertEqual(order.lines.get().quantity, 2)

    def test_concurrent_cancellation_returns_stock_only_once(self):
        order = s.open_table_order(self.tables[0], self.user)
        line = s.add_product_to_order(order, self.product, 1, self.user)
        s.send_order(order, self.user)
        operation = lambda user: s.cancel_sent_line(line, user, "Error")
        self.assertCountEqual(self.concurrent([operation, operation]), [True, False])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(InventoryMovement.objects.filter(movement_type="CANCELLATION_RETURN").count(), 1)
