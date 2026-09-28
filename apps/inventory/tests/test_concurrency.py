from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connections
from django.test import TransactionTestCase

from apps.audit.models import AuditLog
from apps.catalog.models import Category, Product
from apps.inventory.models import InventoryMovement
from apps.inventory.services import adjust_stock, receive_stock


class InventoryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username="concurrency-admin")
        category = Category.objects.create(name="Pruebas", slug="pruebas")
        self.product = Product.objects.create(category=category, name="Producto", slug="producto", track_inventory=True)

    def concurrent_operations(self, operation):
        barrier = Barrier(2)

        def worker():
            try:
                user = get_user_model().objects.get(pk=self.user.pk)
                product = Product.objects.get(pk=self.product.pk)
                barrier.wait(timeout=5)
                try:
                    operation(product, user)
                    return True
                except ValidationError:
                    return False
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            return [future.result(timeout=15) for future in futures]

    def test_simultaneous_receipts_do_not_lose_updates(self):
        results = self.concurrent_operations(lambda product, user: receive_stock(product, 5, user=user))
        self.assertEqual(results, [True, True])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 10)
        self.assertEqual(list(InventoryMovement.objects.order_by("pk").values_list("stock_before", "stock_after")), [(0, 5), (5, 10)])
        self.assertEqual(AuditLog.objects.count(), 2)

    def test_simultaneous_decreases_cannot_overdraw_stock(self):
        receive_stock(self.product, 5, user=self.user)
        results = self.concurrent_operations(lambda product, user: adjust_stock(product, -4, user=user, reason="Conteo"))
        self.assertCountEqual(results, [True, False])
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 1)
        self.assertEqual(InventoryMovement.objects.filter(movement_type="ADJUSTMENT").count(), 1)
