from importlib import reload

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client, override_settings
from django.urls import Resolver404, clear_url_caches, resolve

from apps.catalog.services import update_area_price
from apps.inventory.models import InventoryMovement

from .base import CatalogTestCase


@override_settings(DEBUG=True, ROOT_URLCONF="config.urls")
class CatalogInventoryViewTests(CatalogTestCase):
    def setUp(self):
        import config.urls
        reload(config.urls)
        clear_url_caches()

    def tearDown(self):
        import config.urls
        with override_settings(DEBUG=False):
            reload(config.urls)
        clear_url_caches()

    def inventory_data(self, product, **changes):
        return {"product": product.pk, "movement_type": "RECEIPT", "quantity_delta": 5, "reason": "Compra", **changes}

    def test_anonymous_redirected_to_admin_login(self):
        for url in ("/dev/catalogo/", "/dev/inventario/"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/admin/login/", response.url)

    def test_nonstaff_and_staff_without_permissions_denied(self):
        for staff in (False, True):
            user = get_user_model().objects.create_user(username=f"limited-{staff}", is_staff=staff)
            if not staff:
                user.user_permissions.add(Permission.objects.get(codename="view_product"), Permission.objects.get(codename="view_inventory"))
            self.client.force_login(user)
            for url in ("/dev/catalogo/", "/dev/inventario/"):
                with self.assertLogs("django.request", level="WARNING"):
                    self.assertEqual(self.client.get(url).status_code, 403)

    def test_catalog_shows_optional_area_price_and_no_image_product(self):
        product = self.product()
        update_area_price(product, self.area, "40.00", user=self.user)
        self.client.force_login(self.user)
        response = self.client.get("/dev/catalogo/", {"area": self.area.pk})
        self.assertEqual(response.status_code, 200)
        for text in ("Producto", "Precio general", "Q25", "Q40", "Sin preparación"):
            self.assertContains(response, text)
        self.assertTemplateUsed(response, "base.html")

    def test_bad_area_selection_is_rejected(self):
        self.client.force_login(self.user)
        with self.assertLogs("django.request", level="WARNING"):
            response = self.client.get("/dev/catalogo/", {"area": "invalid"})
        self.assertEqual(response.status_code, 400)

    def test_inventory_shows_all_derived_states(self):
        self.product(slug="free")
        self.product(slug="empty", track_inventory=True)
        self.product(slug="low", track_inventory=True, stock_quantity=1, minimum_stock=1)
        self.product(slug="available", track_inventory=True, stock_quantity=2)
        self.client.force_login(self.user)
        response = self.client.get("/dev/inventario/")
        for text in ("Sin control", "Agotado", "Stock bajo", "Disponible"):
            self.assertContains(response, text)

    def test_inventory_post_records_receipt_then_adjustment(self):
        product = self.product(track_inventory=True)
        self.client.force_login(self.user)
        response = self.client.post("/dev/inventario/", self.inventory_data(product))
        self.assertEqual(response.status_code, 302)
        response = self.client.post("/dev/inventario/", self.inventory_data(
            product, movement_type="ADJUSTMENT", quantity_delta=-2, reason="Rotura",
        ))
        self.assertEqual(response.status_code, 302)
        product.refresh_from_db()
        self.assertEqual(product.stock_quantity, 3)
        self.assertEqual(InventoryMovement.objects.count(), 2)

    def test_inventory_get_never_changes_stock(self):
        product = self.product(track_inventory=True)
        self.client.force_login(self.user)
        response = self.client.get("/dev/inventario/", self.inventory_data(product))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_insufficient_stock_is_a_form_error(self):
        product = self.product(track_inventory=True)
        self.client.force_login(self.user)
        with self.assertLogs("django.request", level="WARNING"):
            response = self.client.post("/dev/inventario/", self.inventory_data(
                product, movement_type="ADJUSTMENT", quantity_delta=-2,
            ))
        self.assertContains(response, "El ajuste dejaría existencias negativas.", status_code=400)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_view_only_user_cannot_submit_a_movement(self):
        product = self.product(track_inventory=True)
        user = get_user_model().objects.create_user(username="viewer", is_staff=True)
        user.user_permissions.add(Permission.objects.get(codename="view_inventory"))
        self.client.force_login(user)
        self.assertNotContains(self.client.get("/dev/inventario/"), "Registrar movimiento")
        with self.assertLogs("django.request", level="WARNING"):
            response = self.client.post("/dev/inventario/", self.inventory_data(product))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_inventory_post_requires_csrf(self):
        product = self.product(track_inventory=True)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        with self.assertLogs("django.security.csrf", level="WARNING"):
            response = client.post("/dev/inventario/", self.inventory_data(product))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(InventoryMovement.objects.count(), 0)

    def test_debug_false_disables_views_and_removes_routes(self):
        import config.urls
        self.client.force_login(self.user)
        try:
            with override_settings(DEBUG=False):
                for url in ("/dev/catalogo/", "/dev/inventario/"):
                    self.assertEqual(self.client.get(url).status_code, 404)
                reload(config.urls)
                clear_url_caches()
                for url in ("/dev/catalogo/", "/dev/inventario/"):
                    with self.assertRaises(Resolver404):
                        resolve(url)
        finally:
            reload(config.urls)
            clear_url_caches()
