from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.operations.models import OperationalDevice, PinAttempt, OperationalSession
from apps.operations.security import DEVICE_COOKIE, SESSION_COOKIE, DEVICE_SALT, LOCKED_MESSAGE
from .base import OperationsTestCase


class DeviceTests(OperationsTestCase):
    def test_device_type_area_and_unique_code(self):
        self.assertEqual(self.device.device_type, "WAITER_TABLET")
        self.assertEqual(self.device.area, self.area)
        with self.assertRaises(ValidationError):
            OperationalDevice.objects.create(name="Duplicado", code=self.device.code, area=self.area)
        with self.assertRaises(ValidationError):
            OperationalDevice.objects.create(name="Sin área", code="NO-AREA")
        with self.assertRaises(ValidationError):
            OperationalDevice.objects.create(name="Caja", code="NO-TYPE", area=self.area, device_type="CASH_REGISTER")

    def test_unconfigured_shows_clean_message(self):
        response = self.client.get("/operacion/acceso/")
        self.assertContains(response, "Este dispositivo aún no está configurado.")
        self.assertNotContains(response, self.waiter.get_full_name())
        self.assertEqual(self.login().status_code, 403)

    def test_configuration_requires_staff_and_specific_permission(self):
        self.assertEqual(self.client.get("/dispositivo/configurar/").status_code, 302)
        self.client.force_login(self.waiter)
        self.assertEqual(self.client.get("/dispositivo/configurar/").status_code, 403)
        staff = get_user_model().objects.create_user(username="staff-device", is_staff=True, role="GERENTE")
        self.client.force_login(staff)
        self.assertEqual(self.client.post("/dispositivo/configurar/", {"device": self.device.pk}).status_code, 403)
        staff.user_permissions.add(Permission.objects.get(codename="configure_operational_device", content_type__app_label="operations"))
        self.assertEqual(self.client.post("/dispositivo/configurar/", {"device": self.device.pk}).status_code, 302)
        self.assertIn(DEVICE_COOKIE, self.client.cookies)

    def test_binding_is_signed_persistent_and_httponly(self):
        self.bind()
        cookie = self.client.cookies[DEVICE_COOKIE]
        payload = signing.loads(cookie.value, salt=DEVICE_SALT)
        self.assertEqual(payload["device_id"], self.device.pk)
        self.assertEqual(payload["version"], str(self.device.binding_version))
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["max-age"], settings.OPERATIONAL_DEVICE_COOKIE_AGE)
        self.assertContains(self.client.get("/operacion/acceso/"), "Sport Bar")
        self.assertTrue(AuditLog.objects.filter(action="operations.browser_configured").exists())

    def test_tampered_cookie_does_not_identify_device(self):
        self.bind()
        self.client.cookies[DEVICE_COOKIE] = self.client.cookies[DEVICE_COOKIE].value + "x"
        self.assertContains(self.client.get("/operacion/acceso/"), "Este dispositivo aún no está configurado.")
        self.assertEqual(self.login().status_code, 403)

    def test_unsigned_id_is_not_a_device_binding(self):
        self.client.cookies[DEVICE_COOKIE] = str(self.device.pk)
        self.assertEqual(self.login().status_code, 403)

    def test_disabled_device_invalidates_existing_access(self):
        self.enter()
        self.device.is_active = False
        self.device.save()
        self.assertEqual(self.client.get("/operacion/mesas/", HTTP_ACCEPT="application/json").status_code, 401)
        self.assertContains(self.client.get("/operacion/acceso/"), "Este dispositivo aún no está configurado.")
        self.assertIsNotNone(OperationalSession.objects.get().revoked_at)
        self.device.is_active = True
        self.device.save()
        self.assertEqual(self.login().status_code, 403)

    def test_area_change_requires_reconfiguration_and_revokes_session(self):
        self.enter()
        self.device.area = self.other_area
        self.device.save(update_fields=["area"])
        self.assertEqual(self.client.get("/operacion/mesas/", HTTP_ACCEPT="application/json").status_code, 401)
        self.assertEqual(self.login().status_code, 403)
        self.bind()
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(OperationalSession.objects.filter(revoked_at__isnull=True).get().area, self.other_area)

    def test_inactive_area_or_invalid_device_cannot_be_configured(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.post("/dispositivo/configurar/", {"device": 999999}).status_code, 200)
        self.area.is_active = False
        self.area.save()
        response = self.client.post("/dispositivo/configurar/", {"device": self.device.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(DEVICE_COOKIE, response.cookies)

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_production_cookies_are_secure(self):
        self.bind()
        self.assertTrue(self.client.cookies[DEVICE_COOKIE]["secure"])
        self.login()
        self.assertTrue(self.client.cookies[SESSION_COOKIE]["secure"])


class PinAccessTests(OperationsTestCase):
    def test_selector_only_lists_active_waiters_with_view_permission(self):
        inactive = self.make_waiter("inactive", "Oculto", "Inactivo", "1234")
        inactive.is_active = False; inactive.save()
        no_permission = get_user_model().objects.create_user(username="no-tables", first_name="Sin permiso", role="MESERO")
        for role in ("GUARDIA", "PROPIETARIO", "GERENTE", "CAJERO"):
            get_user_model().objects.create_user(username=role.lower(), first_name=role, role=role)
        self.bind()
        response = self.client.get("/operacion/acceso/")
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="pin"')
        for hidden in ("Oculto Inactivo", "Sin permiso", "GUARDIA", "PROPIETARIO", "GERENTE", "CAJERO", self.waiter.pin_hash):
            self.assertNotContains(response, hidden)

    def test_correct_pin_creates_separate_session_with_device_user_area(self):
        self.bind()
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"next": "/operacion/mesas/"})
        session = OperationalSession.objects.get()
        self.assertEqual(session.user, self.waiter)
        self.assertEqual(session.area, self.area)
        self.assertEqual(session.device, self.device)
        self.assertNotEqual(session.token_hash, self.client.cookies[SESSION_COOKIE].value)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotContains(self.client.get("/operacion/mesas/"), self.waiter.pin_hash)
        self.assertNotIn("pin", str(AuditLog.objects.filter(action="operations.access_granted").get().data))

    def test_wrong_pin_does_not_echo_pin_or_create_session(self):
        self.bind()
        response = self.login(pin="9999")
        self.assertEqual(response.status_code, 400)
        self.assertNotIn("9999", response.content.decode())
        self.assertFalse(OperationalSession.objects.exists())
        self.assertEqual(PinAttempt.objects.get().failed_attempts, 1)

    def test_pin_accepts_only_four_to_six_ascii_digits(self):
        self.bind()
        for pin in ("123", "1234567", "abcd", "１２３４"):
            with self.subTest(pin=pin):
                self.assertEqual(self.login(pin=pin).status_code, 400)
        self.waiter.set_pin("123456"); self.waiter.save()
        self.assertEqual(self.login(pin="123456").status_code, 200)

    def test_inactive_role_changed_and_missing_pin_cannot_login(self):
        self.bind()
        self.waiter.is_active = False; self.waiter.save()
        self.assertEqual(self.login().status_code, 403)
        self.waiter.is_active = True; self.waiter.role = "GUARDIA"; self.waiter.save()
        self.assertEqual(self.login().status_code, 403)
        self.waiter.role = "MESERO"; self.waiter.pin_hash = ""; self.waiter.save()
        self.assertEqual(self.login().status_code, 400)

    def test_five_failures_lock_for_device_user_and_survive_refresh(self):
        self.bind()
        for attempt in range(5):
            response = self.login(pin="9999")
            self.assertEqual(response.status_code, 429 if attempt == 4 else 400)
        self.assertEqual(response.json()["message"], LOCKED_MESSAGE)
        self.client.get("/operacion/acceso/")
        self.assertEqual(self.login().status_code, 429)
        self.assertEqual(PinAttempt.objects.get().failed_attempts, 5)

    def test_other_user_and_other_device_are_not_locked(self):
        self.bind()
        for _ in range(5): self.login(pin="9999")
        self.assertEqual(self.login(user=self.second_waiter, pin="4632").status_code, 200)
        other_device = OperationalDevice.objects.create(name="Tablet 2", code="TAB-2", area=self.area)
        other_client = self.bind(Client(), other_device)
        self.assertEqual(self.login(other_client).status_code, 200)

    def test_block_expires_after_five_minutes_and_success_resets_attempts(self):
        self.bind()
        for _ in range(5): self.login(pin="9999")
        with patch("apps.operations.security.timezone.now", return_value=timezone.now() + timedelta(seconds=301)):
            self.assertEqual(self.login().status_code, 200)
        attempt = PinAttempt.objects.get()
        self.assertEqual(attempt.failed_attempts, 0)
        self.assertIsNone(attempt.locked_until)

    def test_success_before_lock_resets_failure_counter(self):
        self.bind()
        self.login(pin="9999")
        self.login()
        self.assertEqual(PinAttempt.objects.get().failed_attempts, 0)


class OperationalSessionTests(OperationsTestCase):
    def test_timeout_rejects_backend_open_and_heartbeat(self):
        self.enter()
        OperationalSession.objects.update(last_activity_at=timezone.now() - timedelta(seconds=121))
        self.assertEqual(self.open_table().status_code, 401)
        self.assertEqual(self.client.post("/operacion/actividad/", HTTP_ACCEPT="application/json").status_code, 401)
        self.assertFalse(self.table.primary_orders.exists())

    def test_activity_extends_only_a_still_valid_session(self):
        self.enter()
        before = timezone.now() - timedelta(seconds=90)
        OperationalSession.objects.update(last_activity_at=before)
        self.assertEqual(self.client.post("/operacion/actividad/", HTTP_ACCEPT="application/json").status_code, 200)
        self.assertGreater(OperationalSession.objects.get().last_activity_at, before)

    def test_change_user_preserves_device_and_admin_session(self):
        self.bind(keep_admin=True)
        device_cookie = self.client.cookies[DEVICE_COOKIE].value
        self.login()
        response = self.client.post("/operacion/bloquear/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.cookies[DEVICE_COOKIE].value, device_cookie)
        self.assertEqual(int(self.client.session["_auth_user_id"]), self.user.pk)
        self.assertIsNotNone(OperationalSession.objects.get().revoked_at)
        self.assertEqual(self.login(user=self.second_waiter, pin="4632").status_code, 200)
        self.assertEqual(OperationalSession.objects.get(revoked_at__isnull=True).user, self.second_waiter)

    def test_operational_cookie_cannot_be_used_with_another_browser_binding(self):
        self.enter()
        second = self.bind(Client())
        second.cookies[SESSION_COOKIE] = self.client.cookies[SESSION_COOKIE].value
        self.assertEqual(second.get("/operacion/mesas/", HTTP_ACCEPT="application/json").status_code, 401)

    def test_new_access_in_same_browser_revokes_previous_token(self):
        self.enter()
        previous = self.client.cookies[SESSION_COOKIE].value
        self.assertEqual(self.login(user=self.second_waiter, pin="4632").status_code, 200)
        self.assertEqual(OperationalSession.objects.filter(revoked_at__isnull=True).count(), 1)
        self.client.cookies[SESSION_COOKIE] = previous
        self.assertEqual(self.client.get("/operacion/mesas/", HTTP_ACCEPT="application/json").status_code, 401)

    def test_pin_change_and_permission_removal_revoke_access(self):
        self.enter()
        self.waiter.set_pin("6789"); self.waiter.save()
        self.assertEqual(self.client.get("/operacion/mesas/", HTTP_ACCEPT="application/json").status_code, 401)
        self.login(pin="6789")
        self.waiter.user_permissions.clear()
        self.assertEqual(self.open_table().status_code, 401)

    def test_get_cannot_lock_login_or_mutate_activity(self):
        self.enter()
        self.assertEqual(self.client.get("/operacion/bloquear/").status_code, 405)
        self.assertEqual(self.client.get("/operacion/actividad/").status_code, 405)
        self.assertEqual(self.client.get(f"/operacion/mesas/{self.table.pk}/abrir/").status_code, 405)
        self.assertEqual(self.client.get("/operacion/acceso/").status_code, 302)

    def test_csrf_required_for_access_configuration_open_and_lock(self):
        bound = self.bind(Client())
        client = Client(enforce_csrf_checks=True)
        client.cookies[DEVICE_COOKIE] = bound.cookies[DEVICE_COOKIE].value
        for url, data in (("/operacion/acceso/", {"user_id": self.waiter.pk, "pin": "2580"}),
                          ("/operacion/bloquear/", {}), ("/operacion/actividad/", {}),
                          (f"/operacion/mesas/{self.table.pk}/abrir/", {"billing_mode": "SINGLE"})):
            with self.subTest(url=url):
                self.assertEqual(client.post(url, data).status_code, 403)
        client.force_login(self.user)
        self.assertEqual(client.post("/dispositivo/configurar/", {"device": self.device.pk}).status_code, 403)

    @override_settings(DEBUG=False)
    def test_operational_routes_exist_outside_debug_and_are_not_cacheable(self):
        self.enter()
        response = self.client.get("/operacion/mesas/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("no-store", response["Cache-Control"])
