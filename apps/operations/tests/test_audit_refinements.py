from decimal import Decimal
from django.core.exceptions import ValidationError
from apps.catalog.models import Product, RecipeIngredient, ComboComponent
from apps.catalog.services import is_product_available
from apps.inventory.models import InventoryMovement
from apps.orders import services as orders
from apps.orders.tests.base import OrdersTestCase
from apps.operations.management.recipe_views import save_ingredient
from apps.tables.models import VenueTable
from apps.tables.layout import overlaps
from apps.tables.management_services import arrange_tables
from .test_administration import AdministrationCase


class ManagerRefinementTests(AdministrationCase):
    def test_zero_count_and_repeated_confirmation(self):
        page = self.client.post(self.url('inventory-count'), {'product': self.product.pk, 'quantity': 0, 'note': 'Conteo físico'})
        self.assertEqual(page.status_code, 200)
        token = page.context['review']['signed']
        for _ in range(2): self.assertEqual(self.client.post(self.url('inventory-count'), {'confirmation': token}).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 0)
        self.assertEqual(InventoryMovement.objects.count(), 1)
        self.assertEqual(InventoryMovement.objects.get().quantity_delta, -4)

    def test_stale_confirmation_preserves_input(self):
        page = self.client.post(self.url('inventory-receive'), {'product': self.product.pk, 'quantity': 5, 'note': 'Factura 123'})
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        response = self.client.post(self.url('inventory-receive'), {'confirmation': page.context['review']['signed']})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.context['form'].initial['quantity'], 5)
        self.assertEqual(response.context['form'].initial['note'], 'Factura 123')
        self.assertFalse(InventoryMovement.objects.exists())

    def test_scanned_package_purchase_keeps_cost_and_reference(self):
        self.product.barcode='000123'; self.product.purchase_size=24; self.product.save()
        response=self.client.post(self.url('inventory-receive'), {'barcode':'000123','quantity':2,'receipt_unit':'package','supplier':'Proveedor','invoice':'F123','total_cost':'240'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['review']['after'],52)
        self.client.post(self.url('inventory-receive'),{'confirmation':response.context['review']['signed']})
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity,52)
        self.assertEqual(self.product.last_unit_cost,Decimal('5'))
        self.assertEqual(InventoryMovement.objects.get().metadata['invoice'],'F123')

    def test_batch_limits_and_pdf(self):
        self.product.barcode='0001'; self.product.save()
        response=self.client.post(self.url('label-batch'),{'products':[self.product.pk],'copies':2})
        self.assertEqual(response.status_code,200); self.assertTrue(response.content.startswith(b'%PDF'))
        self.assertEqual(self.client.post(self.url('label-batch'),{'products':[self.product.pk],'copies':201}).status_code,400)

    def test_arrangement_rejects_stale_preview(self):
        a=VenueTable.objects.create(area=self.area,name='A',capacity=4)
        b=VenueTable.objects.create(area=self.area,name='B',capacity=4)
        self.assertEqual(len(overlaps([a,b])),1)
        revision={str(t.pk):t.updated_at.isoformat() for t in [a,b]}
        arrange_tables(self.area,actor=self.manager,revisions=revision)
        self.assertFalse(overlaps(self.area.tables.all()))
        with self.assertRaises(ValidationError):arrange_tables(self.area,actor=self.manager,revisions=revision)

    def test_credential_labels_match_required_fields(self):
        page=self.client.get(self.url('user-create'))
        self.assertTrue(page.context['form'].fields['pin'].required)
        self.assertTrue(page.context['form'].fields['confirm'].required)


class RecipeInventoryTests(OrdersTestCase):
    def setUp(self):
        self.ingredient=Product.objects.create(category=self.category,name='Ron en ml',slug='ron-ml',track_inventory=True,stock_quantity=750,inventory_unit='ml',visible_in_pos=False)
        self.drink=Product.objects.create(category=self.category,name='Mojito',slug='mojito',uses_recipe=True,base_price=40,preparation_route='AREA_BAR')
        self.recipe=RecipeIngredient.objects.create(product=self.drink,ingredient=self.ingredient,quantity=45)

    def test_sale_uses_recipe_but_prints_one_drink_and_cancels_original_quantity(self):
        order=self.open();line=orders.add_product_to_order(order,self.drink,2,self.user)
        ticket=orders.send_order(order,self.user)
        self.ingredient.refresh_from_db();self.assertEqual(self.ingredient.stock_quantity,660)
        self.assertEqual(ticket.items.count(),1);self.assertEqual(ticket.items.get().quantity,2)
        self.recipe.quantity=60;self.recipe.save()
        orders.cancel_sent_line(line,self.user,'Error de pedido')
        self.ingredient.refresh_from_db();self.assertEqual(self.ingredient.stock_quantity,750)

    def test_empty_recipe_and_stock_limit(self):
        Product.objects.filter(pk=self.ingredient.pk).update(stock_quantity=44)
        self.assertFalse(is_product_available(self.drink))
        Product.objects.filter(pk=self.ingredient.pk).update(stock_quantity=750)
        self.recipe.delete()
        self.assertFalse(is_product_available(self.drink))

    def test_insufficient_shared_ingredient_rolls_back_whole_order(self):
        order=self.open();orders.add_product_to_order(order,self.drink,17,self.user)
        with self.assertRaises(ValidationError):orders.send_order(order,self.user)
        self.ingredient.refresh_from_db();self.assertEqual(self.ingredient.stock_quantity,750)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_recipe_in_combo_and_shared_ingredient_snapshot(self):
        combo=Product.objects.create(category=self.category,name='Combo bebidas',slug='combo-drinks',is_combo=True,base_price=75)
        ComboComponent.objects.create(combo=combo,component=self.drink,quantity=2)
        ComboComponent.objects.create(combo=combo,component=self.ingredient,quantity=10)
        order=self.open();line=orders.add_product_to_order(order,combo,1,self.user)
        self.assertEqual(line.components.get(product=self.ingredient).quantity_per_unit,100)
        orders.send_order(order,self.user)
        self.ingredient.refresh_from_db();self.assertEqual(self.ingredient.stock_quantity,650)

    def test_cannot_reinterpret_units_or_disable_used_ingredient(self):
        self.ingredient.inventory_unit='unit'
        with self.assertRaises(ValidationError):self.ingredient.full_clean()
        self.ingredient.inventory_unit='ml';self.ingredient.track_inventory=False;self.ingredient.stock_quantity=0
        with self.assertRaises(ValidationError):self.ingredient.full_clean()

    def test_recipe_cannot_use_itself_or_nested_recipe(self):
        with self.assertRaises(ValidationError):RecipeIngredient.objects.create(product=self.drink,ingredient=self.drink,quantity=1)


    def test_refund_restores_selected_original_ingredient_quantity(self):
        from apps.payments import services as payments
        order=self.open();line=orders.add_product_to_order(order,self.drink,2,self.user)
        orders.send_order(order,self.user)
        payment=payments.pay_full_balance(order,'CARD',self.user,card_approved=True)
        self.recipe.quantity=60;self.recipe.save()
        allocation=payment.allocations.order_by('unit_number').first()
        payments.refund_payment(payment,self.user,allocation_ids=[allocation.pk],return_to_inventory=True,reason='Bebida no preparada')
        self.ingredient.refresh_from_db();self.assertEqual(self.ingredient.stock_quantity,705)
        self.assertEqual(InventoryMovement.objects.get(movement_type='REFUND_RETURN').quantity_delta,45)

    def test_remove_recipe_ingredient_through_manager_service(self):
        save_ingredient(self.drink.pk,{'ingredient':self.ingredient,'quantity':45},user=self.user,remove=True)
        self.assertFalse(RecipeIngredient.objects.filter(product=self.drink).exists())
