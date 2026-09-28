from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError

from apps.audit.models import AuditLog
from apps.catalog.models import Category, ComboComponent, ProductAreaPrice, ProductPriceHistory
from apps.catalog.services import (get_combo_max_available, get_product_price, get_sellable_products,
                                   is_combo_available, is_product_available, update_area_price, update_base_price)

from .base import CatalogTestCase


class PriceServiceTests(CatalogTestCase):
    def test_override_and_fallback(self):
        product = self.product()
        self.assertEqual(get_product_price(product, self.area), Decimal("25.00"))
        update_area_price(product, self.area, "30.00", user=self.user)
        self.assertEqual(get_product_price(product, self.area), Decimal("30.00"))
        self.assertEqual(get_product_price(product), Decimal("25.00"))

    def test_base_price_history_and_audit(self):
        product = self.product()
        update_base_price(product, "27.50", user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.base_price, Decimal("27.50"))
        history = ProductPriceHistory.objects.get()
        self.assertEqual(history.old_price, Decimal("25.00"))
        self.assertEqual(history.new_price, Decimal("27.50"))
        self.assertIsNone(history.area)
        self.assertEqual(history.changed_by, self.user)
        self.assertEqual(AuditLog.objects.get().data["new_price"], "27.50")

    def test_area_creation_and_changes_record_history(self):
        product = self.product()
        update_area_price(product, self.area, "30.00", user=self.user)
        self.assertIsNone(ProductPriceHistory.objects.get().old_price)
        update_area_price(product, self.area, "35.00", user=self.user)
        latest = ProductPriceHistory.objects.first()
        self.assertEqual(latest.area, self.area)
        self.assertEqual(latest.old_price, Decimal("30.00"))
        self.assertEqual(latest.new_price, Decimal("35.00"))
        self.assertEqual(ProductAreaPrice.objects.count(), 1)

    def test_no_op_does_not_duplicate_history(self):
        product = self.product()
        update_base_price(product, 25, user=self.user)
        self.assertEqual(ProductPriceHistory.objects.count(), 0)
        update_area_price(product, self.area, 30, user=self.user)
        update_area_price(product, self.area, 30, user=self.user)
        self.assertEqual(ProductPriceHistory.objects.count(), 1)

    def test_invalid_price_not_saved(self):
        product = self.product()
        for price in ("-1", "1.001", "NaN", "Infinity"):
            with self.subTest(price=price), self.assertRaises(ValidationError):
                update_base_price(product, price, user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.base_price, Decimal("25.00"))
        self.assertEqual(ProductPriceHistory.objects.count(), 0)

    def test_price_permission_required_regardless_of_role(self):
        user = get_user_model().objects.create_user(username="owner", role="PROPIETARIO")
        product = self.product()
        with self.assertRaises(PermissionDenied):
            update_base_price(product, 30, user=user)
        with self.assertRaises(PermissionDenied):
            update_area_price(product, self.area, 30, user=user)

    def test_audit_failure_rolls_back_price_and_history(self):
        product = self.product()
        with patch("apps.catalog.services.AuditLog.objects.create", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                update_base_price(product, 30, user=self.user)
            with self.assertRaises(RuntimeError):
                update_area_price(product, self.area, 40, user=self.user)
        product.refresh_from_db()
        self.assertEqual(product.base_price, Decimal("25.00"))
        self.assertEqual(ProductPriceHistory.objects.count(), 0)
        self.assertEqual(ProductAreaPrice.objects.count(), 0)


class AvailabilityServiceTests(CatalogTestCase):
    def test_sellable_products_filter_category_stock_visibility_and_activity(self):
        normal = self.product()
        tracked = self.product(slug="tracked", track_inventory=True, stock_quantity=1)
        self.product(slug="empty", track_inventory=True)
        self.product(slug="hidden", visible_in_pos=False)
        self.product(slug="inactive", is_active=False)
        other_category = Category.objects.create(name="Otra", slug="otra")
        other = self.product(slug="other", category=other_category)
        self.assertEqual(set(get_sellable_products()), {normal, tracked, other})
        self.assertEqual(set(get_sellable_products(category=self.category, area=self.area)), {normal, tracked})

    def combo_setup(self):
        bottle = self.product(slug="bottle", track_inventory=True, stock_quantity=10)
        energy = self.product(slug="energy", track_inventory=True, stock_quantity=30, visible_in_pos=False)
        combo = self.product(slug="combo", is_combo=True)
        ComboComponent.objects.create(combo=combo, component=bottle, quantity=1)
        ComboComponent.objects.create(combo=combo, component=energy, quantity=4)
        return combo, energy

    def test_combo_maximum_is_limited_by_components(self):
        combo, _ = self.combo_setup()
        self.assertEqual(get_combo_max_available(combo), 7)
        self.assertTrue(is_combo_available(combo))
        self.assertTrue(is_product_available(combo))
        self.assertIn(combo, get_sellable_products())

    def test_combo_insufficient_hidden_component_blocks_availability(self):
        combo, energy = self.combo_setup()
        energy.stock_quantity = 3
        energy.save()
        self.assertEqual(get_combo_max_available(combo), 0)
        self.assertFalse(is_combo_available(combo))
        self.assertNotIn(combo, get_sellable_products())

    def test_empty_combo_unavailable(self):
        combo = self.product(is_combo=True)
        self.assertFalse(is_combo_available(combo))

    def test_untracked_components_have_no_stock_limit(self):
        component = self.product(visible_in_pos=False)
        combo = self.product(slug="combo", is_combo=True)
        ComboComponent.objects.create(combo=combo, component=component, quantity=2)
        self.assertIsNone(get_combo_max_available(combo))
        self.assertTrue(is_combo_available(combo))

    def test_inactive_component_or_combo_blocks_availability(self):
        combo, energy = self.combo_setup()
        energy.is_active = False
        energy.save()
        self.assertFalse(is_combo_available(combo))
        energy.is_active = True
        energy.save()
        combo.visible_in_pos = False
        self.assertFalse(is_combo_available(combo))

    def test_stock_is_global_across_area_price_contexts(self):
        product = self.product(track_inventory=True)
        update_area_price(product, self.area, 50, user=self.user)
        self.assertNotIn(product, get_sellable_products(area=self.area))
        self.assertNotIn(product, get_sellable_products())
