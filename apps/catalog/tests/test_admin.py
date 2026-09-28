from decimal import Decimal

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory
from django.urls import reverse

from apps.catalog.models import Category, ComboComponent, ModifierGroup, ModifierOption, Product, ProductAreaPrice, ProductPriceHistory
from apps.inventory.models import InventoryMovement
from apps.inventory.services import receive_stock

from .base import CatalogTestCase


class CatalogAdminTests(CatalogTestCase):
    def setUp(self):
        self.client.force_login(self.user)

    def form_data(self, **changes):
        return {"category": self.category.pk, "name": "Producto", "slug": "producto", "base_price": "25.00",
                "is_active": "on", "visible_in_pos": "on", "track_inventory": "on",
                "minimum_stock": 0, "preparation_route": "NONE", **changes}

    def test_registered_models_and_admin_pages(self):
        product = self.product()
        group = ModifierGroup.objects.create(product=product, name="Opciones")
        option = ModifierOption.objects.create(group=group, name="Normal")
        for model, obj in ((Category, self.category), (Product, product), (ModifierGroup, group), (ModifierOption, option)):
            self.assertIn(model, admin.site._registry)
            for page, args in (("add", []), ("changelist", []), ("change", [obj.pk])):
                with self.subTest(model=model, page=page):
                    self.assertEqual(self.client.get(reverse(f"admin:catalog_{model._meta.model_name}_{page}", args=args)).status_code, 200)

    def test_product_stock_is_readonly_and_forged_field_ignored(self):
        product = self.product(track_inventory=True)
        receive_stock(product, 5, user=self.user)
        url = reverse("admin:catalog_product_change", args=[product.pk])
        response = self.client.get(url)
        self.assertNotContains(response, 'name="stock_quantity"')
        response = self.client.post(url, self.form_data(stock_quantity=999, base_price="30.00"))
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 5)
        self.assertEqual(product.base_price, Decimal("30.00"))
        self.assertEqual(ProductPriceHistory.objects.count(), 1)

    def test_new_product_starts_at_zero_and_price_is_audited(self):
        response = self.client.post(reverse("admin:catalog_product_add"), self.form_data(stock_quantity=999))
        self.assertEqual(response.status_code, 302)
        product = Product.objects.get(slug="producto")
        self.assertEqual(product.stock_quantity, 0)
        self.assertEqual(product.base_price, Decimal("25.00"))
        self.assertEqual(ProductPriceHistory.objects.get().old_price, 0)

    def test_product_change_permission_does_not_grant_price_permission(self):
        product = self.product(track_inventory=True)
        user = get_user_model().objects.create_user(username="editor", is_staff=True)
        user.user_permissions.add(Permission.objects.get(content_type__app_label="catalog", codename="change_product"))
        self.client.force_login(user)
        url = reverse("admin:catalog_product_change", args=[product.pk])
        self.assertNotContains(self.client.get(url), 'name="base_price"')
        response = self.client.post(url, self.form_data(base_price="999.00"))
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.base_price, Decimal("25.00"))
        self.assertEqual(ProductPriceHistory.objects.count(), 0)

    def test_area_price_admin_uses_history(self):
        product = self.product()
        response = self.client.post(reverse("admin:catalog_productareaprice_add"), {
            "product": product.pk, "area": self.area.pk, "price": "35.00",
        })
        self.assertEqual(response.status_code, 302)
        override = ProductAreaPrice.objects.get()
        response = self.client.post(reverse("admin:catalog_productareaprice_change", args=[override.pk]), {"price": "40.00"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ProductPriceHistory.objects.count(), 2)

    def test_history_admin_is_readonly(self):
        product = self.product(track_inventory=True)
        movement = receive_stock(product, 1, user=self.user)
        history = ProductPriceHistory.objects.create(product=product, old_price=10, new_price=20, changed_by=self.user)
        for model, obj in ((InventoryMovement, movement), (ProductPriceHistory, history)):
            prefix = f"admin:{model._meta.app_label}_{model._meta.model_name}"
            self.assertEqual(self.client.get(reverse(prefix + "_change", args=[obj.pk])).status_code, 200)
            self.assertEqual(self.client.post(reverse(prefix + "_change", args=[obj.pk]), {}).status_code, 403)
            self.assertEqual(self.client.post(reverse(prefix + "_delete", args=[obj.pk]), {"post": "yes"}).status_code, 403)
            self.assertEqual(self.client.get(reverse(prefix + "_add")).status_code, 403)

    def test_invalid_image_rejected_by_admin_form(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        form_class = admin.site._registry[Product].get_form(request)
        form = form_class(data=self.form_data(), files={"image": SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")})
        self.assertFalse(form.is_valid())
        self.assertIn("image", form.errors)

    def test_combo_components_can_be_configured_inline(self):
        component = self.product(slug="component", visible_in_pos=False)
        combo = self.product(is_combo=True)
        data = self.form_data(is_combo="on", track_inventory="")
        data.update({
            "combo_components-TOTAL_FORMS": "1", "combo_components-INITIAL_FORMS": "0",
            "combo_components-MIN_NUM_FORMS": "0", "combo_components-MAX_NUM_FORMS": "1000",
            "combo_components-0-component": component.pk, "combo_components-0-quantity": 2,
            "combo_components-0-sort_order": 0,
        })
        response = self.client.post(reverse("admin:catalog_product_change", args=[combo.pk]), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(ComboComponent.objects.get(combo=combo).component, component)

    def test_area_price_admin_requires_dedicated_permission(self):
        user = get_user_model().objects.create_user(username="area-editor", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="add_productareaprice"))
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("admin:catalog_productareaprice_add")).status_code, 403)
