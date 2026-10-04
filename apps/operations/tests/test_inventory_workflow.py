from django.core import signing
from django.core.exceptions import ValidationError
from .test_administration import AdministrationCase
from apps.operations.management.inventory_views import commit_movement
from apps.catalog.models import Product
from apps.inventory.models import InventoryMovement


class GuidedInventoryTests(AdministrationCase):
    def review(self, kind='exit', quantity=2):
        response = self.client.post(self.url('inventory-exit' if kind == 'exit' else 'inventory-receive'),
            {'product': self.product.pk, 'quantity': quantity, 'reason': 'Rotura', 'note': 'Prueba'})
        self.assertEqual(response.status_code, 200)
        return response.context['review']

    def test_review_is_read_only_confirmation_is_idempotent(self):
        review = self.review()
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 4)
        self.assertFalse(InventoryMovement.objects.exists())
        for _ in range(2):
            response = self.client.post(self.url('inventory-exit'), {'confirmation': review['signed']})
            self.assertEqual(response.status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 2)
        self.assertEqual(InventoryMovement.objects.count(), 1)
        self.assertEqual(InventoryMovement.objects.get().metadata['manager_kind'], 'exit')

    def test_receipt_and_changed_balance_require_new_review(self):
        review = self.review('receipt', 5)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=3)
        response = self.client.post(self.url('inventory-receive'), {'confirmation': review['signed']})
        self.assertContains(response, 'cantidad disponible cambió', status_code=400)
        self.assertFalse(InventoryMovement.objects.exists())
        review = self.review('receipt', 5)
        self.assertEqual(self.client.post(self.url('inventory-receive'), {'confirmation': review['signed']}).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 8)

    def test_negative_stock_missing_reason_and_tampering_rejected(self):
        response = self.client.post(self.url('inventory-exit'), {'product': self.product.pk, 'quantity': 9, 'reason': 'Rotura'})
        self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url('inventory-exit'), {'product': self.product.pk, 'quantity': 1, 'reason': 'Otro'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url('inventory-exit'), {'confirmation': 'forged'}).status_code, 400)
        review = self.review('receipt')
        self.assertEqual(self.client.post(self.url('inventory-exit'), {'confirmation': review['signed']}).status_code, 400)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_permission_rechecked_at_confirmation(self):
        review = self.review()
        self.revoke('adjust_inventory')
        self.assertEqual(self.client.post(self.url('inventory-exit'), {'confirmation': review['signed']}).status_code, 403)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 4)

    def test_optional_barcode_generation_unique_code_and_label(self):
        url = self.url('product-barcode', self.product.pk)
        self.assertEqual(self.client.post(url, {'mode': 'generate'}).status_code, 302)
        self.product.refresh_from_db()
        self.assertTrue(self.product.barcode.startswith('BP'))
        pdf = self.client.get(self.url('product-label', self.product.pk))
        self.assertEqual(pdf['Content-Type'], 'application/pdf')
        self.assertTrue(pdf.content.startswith(b'%PDF'))
        self.assertEqual(self.client.post(url, {'mode': 'keep', 'code': '001234567890'}).status_code, 302)
        self.product.refresh_from_db(); self.assertEqual(self.product.barcode, '001234567890')
        other = Product.objects.create(name='Otra', slug='otra', category=self.category)
        response = self.client.post(self.url('product-barcode', other.pk), {'mode': 'keep', 'code': self.product.barcode})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(url, {'mode': 'remove'}).status_code, 302)
        self.product.refresh_from_db(); self.assertIsNone(self.product.barcode)
        self.assertEqual(self.product.stock_quantity, 4)

    def test_barcode_access_and_validation(self):
        self.assertEqual(self.client.post(self.url('product-barcode', self.product.pk), {'mode': 'keep', 'code': '<bad>'}).status_code, 400)
        self.revoke('change_product')
        self.assertEqual(self.client.post(self.url('product-barcode', self.product.pk), {'mode': 'generate'}).status_code, 403)

    def test_review_can_be_corrected_without_writing(self):
        review = self.review()
        response = self.client.post(self.url('inventory-exit'), {'confirmation': review['signed'], 'action': 'edit'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['form'].initial['quantity'], 2)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_code_search_and_manual_exit_filter(self):
        Product.objects.filter(pk=self.product.pk).update(barcode='000123')
        response = self.client.get(self.url('inventory'), {'q': '000123'})
        self.assertEqual(response.context['rows'].paginator.count, 1)
        review = self.review()
        self.client.post(self.url('inventory-exit'), {'confirmation': review['signed']})
        response = self.client.get(self.url('inventory-movements'), {'type': 'MANUAL_EXIT'})
        self.assertContains(response, 'Salida manual')
        self.assertEqual(response.context['rows'].paginator.count, 1)
