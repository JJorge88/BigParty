from importlib import reload

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase, override_settings
from django.urls import Resolver404, clear_url_caches, resolve, reverse

from apps.audit.models import AuditLog
from apps.tables.models import VenueTable
from apps.venues.models import Area, Zone


class TableAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="admin-tables", password="Only-test-72!")
        cls.area = Area.objects.create(name="Discoteca", slug="discoteca")
        cls.zone = Zone.objects.create(area=cls.area, name="VIP", slug="vip")
        cls.other = Area.objects.create(name="Sport Bar", slug="sport-bar")
        cls.other_zone = Zone.objects.create(area=cls.other, name="VIP", slug="vip")
        cls.table = VenueTable.objects.create(area=cls.area, name="Mesa 01", capacity=4)

    def setUp(self):
        self.client.force_login(self.user)

    def form_data(self, **changes):
        return {
            "name": "Mesa 01", "area": self.area.pk, "zone": "", "capacity": 4,
            "operational_status": "ACTIVE", "is_active": "on", "sort_order": 0,
            "layout_x": "0.00", "layout_y": "0.00", "layout_width": "10.00",
            "layout_height": "10.00", "layout_shape": "RECTANGLE", **changes,
        }

    def test_admin_registered_and_pages_render(self):
        self.assertIn(VenueTable, admin.site._registry)
        for page, args in (("changelist", []), ("add", []), ("change", [self.table.pk])):
            with self.subTest(page=page):
                response = self.client.get(reverse(f"admin:tables_venuetable_{page}", args=args))
                self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Distribución visual")

    def test_admin_creates_table(self):
        response = self.client.post(reverse("admin:tables_venuetable_add"), self.form_data(name="Nueva", zone=self.zone.pk))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(VenueTable.objects.filter(name="Nueva", zone=self.zone).exists())

    def test_admin_updates_use_audited_service(self):
        response = self.client.post(reverse("admin:tables_venuetable_change", args=[self.table.pk]), self.form_data(
            capacity=8, operational_status="OUT_OF_SERVICE", reservable_web="on",
        ))
        self.assertEqual(response.status_code, 302)
        self.table.refresh_from_db()
        self.assertEqual(self.table.capacity, 8)
        self.assertEqual(self.table.operational_status, "OUT_OF_SERVICE")
        self.assertEqual(AuditLog.objects.filter(user=self.user, entity_id=str(self.table.pk)).count(), 3)

    def test_admin_invalid_zone_displays_validation_error(self):
        response = self.client.post(
            reverse("admin:tables_venuetable_change", args=[self.table.pk]),
            self.form_data(zone=self.other_zone.pk),
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "La zona debe pertenecer a la misma área que la mesa.")
        self.table.refresh_from_db()
        self.assertIsNone(self.table.zone)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_admin_has_no_direct_or_bulk_delete(self):
        url = reverse("admin:tables_venuetable_delete", args=[self.table.pk])
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
        response = self.client.get(reverse("admin:tables_venuetable_changelist"))
        self.assertNotContains(response, 'value="delete_selected"')
        self.client.post(reverse("admin:tables_venuetable_changelist"), {
            "action": "delete_selected", "_selected_action": [self.table.pk], "post": "yes",
        })
        self.assertTrue(VenueTable.objects.filter(pk=self.table.pk).exists())


@override_settings(DEBUG=True, ROOT_URLCONF="apps.tables.urls")
class DevelopmentViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="staff", is_staff=True)
        cls.area = Area.objects.create(name="Discoteca", slug="discoteca")
        cls.zone = Zone.objects.create(area=cls.area, name="VIP", slug="vip")
        cls.table = VenueTable.objects.create(area=cls.area, zone=cls.zone, name="Mesa 01", capacity=4)

    # La ruta real se incluye condicionalmente en config.urls. Recargar dentro del
    # override permite comprobar ambos modos sin depender del orden del test runner.
    def setUp(self):
        self.settings_override = override_settings(ROOT_URLCONF="config.urls")
        self.settings_override.enable()
        import config.urls
        reload(config.urls)
        clear_url_caches()

    def tearDown(self):
        self.settings_override.disable()
        clear_url_caches()

    def grant_view_permissions(self):
        self.user.user_permissions.add(*Permission.objects.filter(
            codename__in=["view_area", "view_zone", "view_venuetable"],
            content_type__app_label__in=["venues", "tables"],
        ))
        self.client.force_login(self.user)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get("/dev/mesas/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("admin:login") + "?next=/dev/mesas/")

    def test_authenticated_user_without_permissions_denied(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/dev/mesas/").status_code, 403)

    def test_authorized_view_shows_domain_data(self):
        self.grant_view_permissions()
        response = self.client.get("/dev/mesas/")
        self.assertEqual(response.status_code, 200)
        for text in ("Discoteca", "VIP", "Mesa 01", "Capacidad", "Reservable web", "Activa"):
            self.assertContains(response, text)
        self.assertTemplateUsed(response, "base.html")

    def test_disabled_in_non_debug_even_if_url_already_loaded(self):
        self.grant_view_permissions()
        with override_settings(DEBUG=False):
            self.assertEqual(self.client.get("/dev/mesas/").status_code, 404)

    def test_url_absent_when_urlconf_loads_without_debug(self):
        import config.urls
        try:
            with override_settings(DEBUG=False):
                reload(config.urls)
                clear_url_caches()
                with self.assertRaises(Resolver404):
                    resolve("/dev/mesas/")
        finally:
            reload(config.urls)
            clear_url_caches()
