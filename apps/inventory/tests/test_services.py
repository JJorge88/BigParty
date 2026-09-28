from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction

from apps.audit.models import AuditLog
from apps.catalog.tests.base import CatalogTestCase
from apps.inventory.models import InventoryMovement
from apps.inventory.services import adjust_stock, receive_stock


class InventoryServiceTests(CatalogTestCase):
    def test_receipt_changes_stock_and_records_movement_and_audit(self):
        product = self.product(track_inventory=True)
        movement = receive_stock(product, 12, user=self.user, reason="Compra")
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 12)
        self.assertEqual((movement.stock_before, movement.stock_after, movement.quantity_delta), (0, 12, 12))
        self.assertEqual(movement.movement_type, "RECEIPT")
        self.assertEqual(movement.user, self.user)
        self.assertEqual(AuditLog.objects.get().data["movement_id"], movement.pk)
        self.assertTrue(product.is_available_for_sale)

    def test_positive_and_negative_adjustments_use_current_stock(self):
        product = self.product(track_inventory=True, stock_quantity=5)
        adjust_stock(product, 12, user=self.user, reason="Conteo")
        movement = adjust_stock(product, -2, user=self.user, reason="Rotura")
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 15)
        self.assertEqual((movement.stock_before, movement.stock_after), (17, 15))
        self.assertEqual(InventoryMovement.objects.count(), 2)
        self.assertEqual(AuditLog.objects.count(), 2)

    def test_adjustment_to_zero_marks_product_unavailable(self):
        product = self.product(track_inventory=True, stock_quantity=1)
        adjust_stock(product, -1, user=self.user, reason="Pérdida")
        product.refresh_from_db()
        self.assertTrue(product.is_out_of_stock)
        self.assertFalse(product.is_available_for_sale)

    def test_negative_stock_rejected_without_movement(self):
        product = self.product(track_inventory=True, stock_quantity=1)
        with self.assertRaises(ValidationError):
            adjust_stock(product, -2, user=self.user, reason="Rotura")
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 1)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_receipt_accepts_only_positive_whole_units(self):
        product = self.product(track_inventory=True)
        for quantity in (0, -1, 1.5, True, "2", Decimal("2.0")):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                receive_stock(product, quantity, user=self.user)

    def test_adjustment_requires_nonzero_integer_and_reason(self):
        product = self.product(track_inventory=True)
        for delta, reason in ((0, "Motivo"), (1.5, "Motivo"), (True, "Motivo"), (1, ""), (1, "   ")):
            with self.subTest(delta=delta, reason=reason), self.assertRaises(ValidationError):
                adjust_stock(product, delta, user=self.user, reason=reason)

    def test_untracked_products_and_combos_reject_movements(self):
        for product in (self.product(), self.product(slug="combo", is_combo=True)):
            with self.subTest(product=product), self.assertRaises(ValidationError):
                receive_stock(product, 1, user=self.user)

    def test_each_operation_requires_its_own_permission(self):
        user = get_user_model().objects.create_user(username="manager", role="GERENTE")
        product = self.product(track_inventory=True)
        with self.assertRaises(PermissionDenied):
            receive_stock(product, 1, user=user)
        user.user_permissions.add(Permission.objects.get(codename="receive_inventory"))
        user = get_user_model().objects.get(pk=user.pk)
        receive_stock(product, 1, user=user)
        with self.assertRaises(PermissionDenied):
            adjust_stock(product, 1, user=user, reason="Conteo")

    def test_audit_failure_rolls_back_stock_and_movement(self):
        product = self.product(track_inventory=True)
        with patch("apps.inventory.services.AuditLog.objects.create", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                receive_stock(product, 5, user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_invalid_movement_balance_rejected_by_database(self):
        product = self.product(track_inventory=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            InventoryMovement.objects.create(
                product=product, movement_type="RECEIPT", quantity_delta=2, stock_before=0, stock_after=5,
            )
