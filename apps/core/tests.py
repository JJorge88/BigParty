from django.conf import settings
from django.contrib.staticfiles import finders
from django.test import Client, SimpleTestCase
from django.urls import reverse


class FoundationTests(SimpleTestCase):
    def test_home_renders_base_template_in_spanish(self):
        response = self.client.get(reverse("core:home"))
        self.assertContains(response, "BIG PARTY")
        self.assertContains(response, "Sistema en desarrollo")
        self.assertContains(response, '<html lang="es">')
        self.assertTemplateUsed(response, "base.html")

    def test_admin_login_is_available_in_spanish(self):
        response = self.client.get(reverse("admin:login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Administración de BIG PARTY")
        self.assertContains(response, "Nombre de usuario")

    def test_admin_login_rejects_post_without_csrf(self):
        client = Client(enforce_csrf_checks=True)
        self.assertEqual(client.post(reverse("admin:login"), {"username": "test"}).status_code, 403)

    def test_postgresql_and_custom_user_are_configured(self):
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")
        self.assertTrue(settings.USE_TZ)

    def test_global_css_is_available(self):
        self.assertIsNotNone(finders.find("css/base.css"))
