from django.core.exceptions import PermissionDenied
from django.test import override_settings
from apps.catalog.models import Product, Category
from apps.catalog.management_services import save_product
from apps.inventory.models import InventoryMovement
from .test_administration import AdministrationCase


class ManagerWorkflowTests(AdministrationCase):
    def test_hub_and_common_navigation(self):
        response = self.client.get('/gerencia/agregar/')
        for link in ['/gerencia/inventario/producto/crear/', '/gerencia/inventario/entradas/nueva/',
                     '/gerencia/mesas/nueva/', '/gerencia/reservas/nueva/', '/gerencia/eventos/nuevo/', '/gerencia/usuarios/crear/']:
            self.assertContains(response, link)
        for path in ['/gerencia/', '/gerencia/inventario/', '/gerencia/mesas/', '/gerencia/usuarios/',
                     '/gerencia/reservas/', '/gerencia/eventos/', '/gerencia/configuracion/']:
            with self.subTest(path=path):
                self.assertContains(self.client.get(path), 'Más módulos')

    def test_create_product_generates_identifier_and_initial_stock(self):
        data=self.product_data(name='Mojito nuevo', slug='', initial_stock='12', after_save='another')
        response=self.client.post(self.url('product-create'),data)
        self.assertRedirects(response,self.url('product-create'))
        product=Product.objects.get(slug='mojito-nuevo')
        self.assertEqual(product.stock_quantity,12)
        movement=InventoryMovement.objects.get(product=product)
        self.assertEqual(movement.user,self.manager)
        self.assertEqual(movement.quantity_delta,12)
        self.client.post(self.url('product-create'),{**data,'initial_stock':'0'})
        self.assertTrue(Product.objects.filter(slug='mojito-nuevo-2').exists())

    def test_failed_receipt_rolls_back_new_product(self):
        self.revoke('receive_inventory')
        data={'name':'Protegido','slug':'protegido','category':self.category,'track_inventory':True,'initial_stock':7}
        with self.assertRaises(PermissionDenied):
            save_product(data,user=self.manager)
        self.assertFalse(Product.objects.filter(slug='protegido').exists())

    def test_initial_stock_requires_tracking_and_existing_stock_is_preserved(self):
        data=self.product_data(name='Sin conteo',slug='',initial_stock='3')
        data.pop('track_inventory')
        self.assertEqual(self.client.post(self.url('product-create'),data).status_code,400)
        self.assertFalse(Product.objects.filter(name='Sin conteo').exists())
        data=self.product_data(slug='',initial_stock='99')
        self.assertEqual(self.client.post(self.url('product-edit',self.product.pk),data).status_code,302)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity,4)
        self.assertEqual(self.product.slug,'gallo')

    def test_quick_receipt_reuses_inventory_service(self):
        response=self.client.post(self.url('stock-create'),{'product':self.product.pk,'quantity':5,'reason':'Compra','after_save':'another'})
        self.assertRedirects(response,self.url('stock-create'))
        self.product.refresh_from_db();self.assertEqual(self.product.stock_quantity,9)
        self.revoke('receive_inventory')
        self.assertEqual(self.client.post(self.url('stock-create'),{'product':self.product.pk,'quantity':5}).status_code,403)
        self.assertNotContains(self.client.get('/gerencia/agregar/'),'href="/gerencia/inventario/entradas/nueva/"')

    def test_category_identifier_is_optional(self):
        response=self.client.post(self.url('category-create'),{'name':'Bebidas nuevas','slug':'','sort_order':0,'is_active':'on'})
        self.assertEqual(response.status_code,302)
        self.assertTrue(Category.objects.filter(slug='bebidas-nuevas').exists())

    def test_create_tables_and_categories_without_leaving_creation(self):
        response=self.client.get('/gerencia/mesas/nueva/')
        self.assertContains(response,f'/gerencia/mesas/area/{self.area.pk}/crear/')
        response=self.client.post(self.url('table-create',self.area.pk),{'name':'Nueva mesa','capacity':4,
            'layout_shape':'RECTANGLE','layout_x':10,'layout_y':10,'layout_width':15,'layout_height':15,
            'operational_status':'ACTIVE','is_active':'on','after_save':'another'})
        self.assertRedirects(response,self.url('table-create',self.area.pk))
        response=self.client.post(self.url('category-create'),{'name':'Nueva categoría','slug':'','sort_order':0,'is_active':'on','after_save':'another'})
        self.assertRedirects(response,self.url('category-create'))

    @override_settings(SYNC_ENABLED=True,DEPLOYMENT_MODE='cloud')
    def test_hub_respects_sync_authority(self):
        response=self.client.get('/gerencia/agregar/')
        self.assertNotContains(response,'href="/gerencia/inventario/producto/crear/"')
        self.assertContains(response,'href="/gerencia/eventos/nuevo/"')
