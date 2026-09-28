from decimal import Decimal
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.catalog.models import Category, ComboComponent, ModifierGroup, ModifierOption, Product, ProductAreaPrice

from .base import CatalogTestCase


class CategoryAndSeedTests(TestCase):
    def test_creation_uniqueness_and_order(self):
        last = Category.objects.create(name="Última", slug="ultima", sort_order=20)
        first = Category.objects.create(name="Primera", slug="primera", sort_order=10)
        self.assertEqual(list(Category.objects.all()), [first, last])
        self.assertTrue(first.is_active)
        for fields in ({"name": "Primera", "slug": "otra"}, {"name": "Otra", "slug": "primera"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                Category.objects.create(**fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Category.objects.bulk_create([Category(**fields)])

    def test_seed_creates_only_categories_and_is_idempotent(self):
        call_command("seed_catalog_defaults", stdout=StringIO())
        original = list(Category.objects.values_list("pk", "name"))
        call_command("seed_catalog_defaults", stdout=StringIO())
        self.assertEqual(list(Category.objects.values_list("pk", "name")), original)
        self.assertEqual([name for _, name in original], ["Cervezas", "Licores", "Cócteles", "Comida", "Snacks", "Combos"])
        self.assertEqual(Product.objects.count(), 0)

    def test_seed_preserves_existing_customizations(self):
        category = Category.objects.create(name="Personalizada", slug="cervezas", sort_order=99, is_active=False)
        call_command("seed_catalog_defaults", stdout=StringIO())
        category.refresh_from_db()
        self.assertEqual(category.name, "Personalizada")
        self.assertEqual(category.sort_order, 99)
        self.assertFalse(category.is_active)

    def test_seed_conflict_rolls_back(self):
        Category.objects.create(name="Comida", slug="personalizada")
        with self.assertRaises(CommandError):
            call_command("seed_catalog_defaults", stdout=StringIO())
        self.assertEqual(Category.objects.count(), 1)


class ProductModelTests(CatalogTestCase):
    def test_valid_product_defaults_and_optional_image(self):
        product = self.product()
        self.assertEqual(product.base_price, Decimal("25.00"))
        self.assertFalse(product.image)
        self.assertTrue(product.visible_in_pos)
        self.assertEqual(product.preparation_route, Product.PreparationRoute.NONE)
        self.assertTrue(product.is_available_for_sale)

    def test_negative_prices_and_stock_rejected_by_python_and_database(self):
        product = self.product(track_inventory=True)
        for fields in ({"base_price": -1}, {"stock_quantity": -1}, {"minimum_stock": -1}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.product(slug="invalid", **fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                Product.objects.filter(pk=product.pk).update(**fields)

    def test_zero_price_and_minimum_are_valid(self):
        product = self.product(base_price=0, minimum_stock=0)
        self.assertEqual(product.base_price, 0)

    def test_stock_properties_are_derived(self):
        product = self.product(track_inventory=True, stock_quantity=2, minimum_stock=2)
        self.assertTrue(product.is_low_stock)
        self.assertFalse(product.is_out_of_stock)
        self.assertTrue(product.is_available_for_sale)
        product.stock_quantity = 0
        product.save()
        self.assertTrue(product.is_low_stock)
        self.assertTrue(product.is_out_of_stock)
        self.assertFalse(product.is_available_for_sale)

    def test_untracked_product_is_available_without_stock(self):
        product = self.product(track_inventory=False, minimum_stock=10)
        self.assertFalse(product.is_low_stock)
        self.assertFalse(product.is_out_of_stock)
        self.assertTrue(product.is_available_for_sale)

    def test_internal_inactive_and_inactive_category_not_sellable(self):
        product = self.product(visible_in_pos=False)
        self.assertFalse(product.is_available_for_sale)
        product.visible_in_pos = True
        product.is_active = False
        self.assertFalse(product.is_available_for_sale)
        product.is_active = True
        product.category.is_active = False
        self.assertFalse(product.is_available_for_sale)

    def test_preparation_choices(self):
        for index, route in enumerate(Product.PreparationRoute.values):
            self.product(slug=f"route-{index}", preparation_route=route)
        with self.assertRaises(ValidationError):
            self.product(slug="invalid", preparation_route="BAR_1")

    def test_category_delete_is_protected(self):
        self.product()
        with self.assertRaises(ProtectedError):
            self.category.delete()

    def test_cannot_remove_tracking_with_nonzero_stock(self):
        product = self.product(track_inventory=True, stock_quantity=2)
        product.track_inventory = False
        with self.assertRaises(ValidationError):
            product.save()

    def test_combo_cannot_have_own_stock(self):
        for fields in ({"track_inventory": True}, {"stock_quantity": 1}, {"minimum_stock": 1}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.product(is_combo=True, **fields)

    def test_area_price_uniqueness_and_nonnegative(self):
        product = self.product()
        ProductAreaPrice.objects.create(product=product, area=self.area, price=30)
        with self.assertRaises(ValidationError):
            ProductAreaPrice.objects.create(product=product, area=self.area, price=40)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ProductAreaPrice.objects.bulk_create([ProductAreaPrice(product=product, area=self.area, price=40)])
        override = ProductAreaPrice.objects.get(product=product)
        override.price = -1
        with self.assertRaises(ValidationError):
            override.save()


class ModifierAndComboModelTests(CatalogTestCase):
    def test_modifier_group_options_and_extra_price(self):
        group = ModifierGroup.objects.create(product=self.product(), name="Preparación")
        option = ModifierOption.objects.create(group=group, name="Extra queso", price_delta="10.00")
        self.assertEqual(option.price_delta, Decimal("10.00"))
        with self.assertRaises(ValidationError):
            ModifierOption.objects.create(group=group, name="Inválido", price_delta=-1)

    def test_single_multiple_and_required_bounds(self):
        product = self.product()
        invalid = [
            {"max_selections": 2}, {"max_selections": 0}, {"min_selections": -1},
            {"min_selections": 2, "max_selections": 1}, {"is_required": True, "min_selections": 0},
            {"is_required": False, "min_selections": 1}, {"selection_type": "INVALID"},
        ]
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                ModifierGroup.objects.create(product=product, name="Opciones", **fields)
        ModifierGroup.objects.create(product=product, name="Extras", selection_type="MULTIPLE", max_selections=3)
        ModifierGroup.objects.create(product=product, name="Requerido", is_required=True, min_selections=1)

    def test_combo_components_and_hidden_products(self):
        component = self.product(visible_in_pos=False)
        combo = self.product(slug="combo", is_combo=True)
        link = ComboComponent.objects.create(combo=combo, component=component, quantity=2)
        self.assertEqual(link.quantity, 2)
        with self.assertRaises(ValidationError):
            ComboComponent.objects.create(combo=combo, component=component, quantity=1)
        with self.assertRaises(ProtectedError):
            component.delete()

    def test_combo_rejects_self_nesting_noncombo_parent_and_zero_quantity(self):
        component = self.product()
        combo = self.product(slug="combo", is_combo=True)
        other_combo = self.product(slug="combo-other", is_combo=True)
        for fields in (
            {"combo": combo, "component": combo, "quantity": 1},
            {"combo": combo, "component": other_combo, "quantity": 1},
            {"combo": component, "component": combo, "quantity": 1},
            {"combo": combo, "component": component, "quantity": 0},
        ):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                ComboComponent.objects.create(**fields)

    def test_later_product_type_changes_cannot_create_nesting(self):
        component = self.product()
        combo = self.product(slug="combo", is_combo=True)
        ComboComponent.objects.create(combo=combo, component=component, quantity=1)
        component.is_combo = True
        with self.assertRaises(ValidationError):
            component.save()
        combo.is_combo = False
        with self.assertRaises(ValidationError):
            combo.save()
