from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import signing
from django.test import Client, override_settings
from django.utils import timezone

from apps.audit.models import AuditLog
from apps.cash import services
from apps.cash.models import BusinessDay, CashSession, CashMovement, CashHandoff
from apps.cash.tests.base import CashTestCase
from apps.operations import cash_security as security
from apps.operations.models import CashAccessSession, CashPinAttempt


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CashWorkstationTests(CashTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.cashier = get_user_model().objects.create_user(username="carlos", first_name="Carlos", last_name="Méndez", role="CAJERO")
        cls.cashier.set_pin("2580"); cls.cashier.save()
        cls.cashier.user_permissions.add(*Permission.objects.filter(codename__in=["open_cash_session", "receive_waiter_cash", "close_cash_session", "view_cashmovement", "request_cash_withdrawal"]))
        cls.other_cashier = get_user_model().objects.create_user(username="lucia", first_name="Lucía", role="CAJERO")
        cls.other_cashier.set_pin("4632"); cls.other_cashier.save()
        cls.other_cashier.user_permissions.set(cls.cashier.user_permissions.all())
        cls.other_user.set_pin("654321"); cls.other_user.save()

    def setUp(self):
        self.station = self.register("DISCOTECA")
        self.configure()
        self.login()

    def configure(self, client=None, register=None):
        client = client or self.client
        client.force_login(self.user)
        self.assertEqual(client.post("/caja/configurar/", {"register": (register or self.station).pk}).status_code, 302)
        binding = client.cookies[security.REGISTER_COOKIE].value
        client.logout()
        client.cookies[security.REGISTER_COOKIE] = binding
        return client

    def login(self, client=None, user=None, pin="2580"):
        return (client or self.client).post("/caja/acceso/", {"user_id": (user or self.cashier).pk, "pin": pin}, HTTP_ACCEPT="application/json")

    def open_cash(self, amount="500.00", client=None):
        response = (client or self.client).post("/caja/accion/abrir/", {"opening_float": amount}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return CashSession.objects.get(register=self.station, status="OPEN")

    def post(self, action, session, **data):
        return self.client.post(f"/caja/accion/{action}/", {"cash_session": session.pk, **data}, HTTP_ACCEPT="application/json")

    def page(self, screen, json=False):
        return self.client.get(f"/caja/{screen}/", HTTP_ACCEPT="application/json" if json else "text/html")

    def withdrawal(self, session, **data):
        token = self.page("retiro", json=True).json()["withdrawal_token"]
        return self.post("retirar", session, **{"amount": "100", "reason": "Cambio", "approver_id": self.other_user.pk, "approver_pin": "654321", "withdrawal_token": token, **data})

    def pending(self):
        order, _ = self.consumption()
        return self.payment(order).cash_handoff

    def assertPrivate(self, response):
        content = response.content.decode().lower()
        for forbidden in ("expected_cash", "difference", "opening_float", "sales_total", "efectivo esperado", "ventas totales", "total acumulado", "500.00"):
            self.assertNotIn(forbidden, content)
        self.assertEqual(response["Cache-Control"], "max-age=0, no-cache, no-store, must-revalidate, private")

    def test_unconfigured_no_operating_options(self):
        response = Client().get("/caja/", follow=True)
        self.assertContains(response, "Esta computadora aún no está configurada como caja.")
        self.assertNotContains(response, "Venta rápida")

    def test_configure_requires_staff_permission(self):
        self.assertEqual(Client().post("/caja/configurar/", {}).status_code, 302)
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get("/caja/configurar/").status_code, 403)
        self.cashier.is_staff = True; self.cashier.save()
        self.assertEqual(self.client.post("/caja/configurar/", {"register": self.station.pk}).status_code, 403)
        self.cashier.user_permissions.add(Permission.objects.get(codename="configure_cash_register_device"))
        self.assertEqual(self.client.post("/caja/configurar/", {"register": self.station.pk}).status_code, 302)

    def test_binding_cookie_signed_scoped_and_private(self):
        self.client.force_login(self.user)
        response = self.client.post("/caja/configurar/", {"register": self.station.pk})
        cookie = response.cookies[security.REGISTER_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertEqual(cookie["path"], "/caja/")
        self.assertEqual(signing.loads(cookie.value, salt=security.REGISTER_SALT)["register"], self.station.pk)

    @override_settings(SESSION_COOKIE_SECURE=True)
    def test_production_cookies_secure(self):
        self.client.force_login(self.user)
        response = self.client.post("/caja/configurar/", {"register": self.station.pk})
        self.assertTrue(response.cookies[security.REGISTER_COOKIE]["secure"])
        self.assertTrue(self.login().cookies[security.ACCESS_COOKIE]["secure"])

    def test_tampered_binding_rejected(self):
        self.client.cookies[security.REGISTER_COOKIE] = self.client.cookies[security.REGISTER_COOKIE].value + "x"
        self.assertEqual(self.page("activa", True).status_code, 401)

    def test_missing_binding_rejected_even_with_access_token(self):
        del self.client.cookies[security.REGISTER_COOKIE]
        self.assertEqual(self.page("activa", True).status_code, 401)

    def test_inactive_station_revokes_and_reactivation_requires_configuration(self):
        self.station.is_active = False; self.station.save()
        self.assertIsNotNone(CashAccessSession.objects.get().revoked_at)
        self.station.is_active = True; self.station.save()
        self.assertEqual(self.login().status_code, 403)

    def test_inactive_station_cannot_be_configured(self):
        self.station.is_active = False; self.station.save()
        self.client.force_login(self.user)
        response = self.client.post("/caja/configurar/", {"register": self.station.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(security.REGISTER_COOKIE, response.cookies)

    def test_inactive_area_rejected(self):
        self.area.is_active = False; self.area.save()
        self.assertEqual(self.page("activa", True).status_code, 401)

    def test_candidates_only_active_cash_roles_and_permissions(self):
        get_user_model().objects.create_user(username="sin-permiso", role="CAJERO")
        self.client.post("/caja/bloquear/")
        response = self.client.get("/caja/acceso/")
        self.assertContains(response, "Carlos Méndez")
        self.assertContains(response, "Lucía")
        self.assertNotContains(response, "orders-admin")
        self.assertNotContains(response, "sin-permiso")

    def test_operational_login_does_not_login_admin_or_tablet(self):
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertNotIn("bigparty_operation", self.client.cookies)
        access = CashAccessSession.objects.get()
        self.assertEqual(access.business_day, self.day)
        self.assertEqual(access.register, self.station)
        self.assertEqual(access.user, self.cashier)
        self.assertNotEqual(access.token_hash, self.client.cookies[security.ACCESS_COOKIE].value)

    def test_relogin_revokes_previous_token(self):
        previous = self.client.cookies[security.ACCESS_COOKIE].value
        self.login()
        self.client.cookies[security.ACCESS_COOKIE] = previous
        self.assertEqual(self.page("abrir", True).status_code, 401)

    def test_access_token_cannot_move_to_other_browser_binding(self):
        other = self.configure(Client())
        other.cookies[security.ACCESS_COOKIE] = self.client.cookies[security.ACCESS_COOKIE].value
        self.assertEqual(other.get("/caja/abrir/", HTTP_ACCEPT="application/json").status_code, 401)

    def test_wrong_and_malformed_pin(self):
        for pin in ("258", "2580000", "abcd", "１２３４", "9999"):
            response = self.login(pin=pin)
        self.assertEqual(response.status_code, 429)
        self.assertEqual(CashPinAttempt.objects.get(user=self.cashier).failed_attempts, 5)

    def test_lockout_five_failures_and_expiration(self):
        for _ in range(4):
            self.assertEqual(self.login(pin="1111").status_code, 400)
        self.assertEqual(self.login(pin="1111").status_code, 429)
        self.assertEqual(self.login().status_code, 429)
        attempt = CashPinAttempt.objects.get(user=self.cashier)
        self.assertGreater(attempt.locked_until, timezone.now() + timedelta(minutes=4))
        CashPinAttempt.objects.filter(pk=attempt.pk).update(locked_until=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.login().status_code, 200)

    def test_lockout_is_station_and_user_scoped(self):
        for _ in range(5): self.login(pin="1111")
        self.assertEqual(self.login(user=self.other_cashier, pin="4632").status_code, 200)
        other = self.configure(Client(), self.register("PREMIUM", self.other_area))
        self.assertEqual(self.login(client=other).status_code, 200)

    def test_idle_timeout_ten_minutes(self):
        CashAccessSession.objects.update(last_activity_at=timezone.now() - timedelta(minutes=9))
        self.assertEqual(self.page("abrir").status_code, 200)
        CashAccessSession.objects.update(last_activity_at=timezone.now() - timedelta(minutes=10))
        self.assertEqual(self.page("abrir", True).status_code, 401)

    def test_disabled_user_revokes_access(self):
        self.cashier.is_active = False; self.cashier.save()
        self.assertEqual(self.page("abrir", True).status_code, 401)

    def test_pin_change_revokes_access(self):
        self.cashier.set_pin("1111"); self.cashier.save()
        self.assertEqual(self.page("abrir", True).status_code, 401)

    def test_activity_requires_access_and_refreshes_it(self):
        old = timezone.now() - timedelta(minutes=3)
        CashAccessSession.objects.update(last_activity_at=old)
        self.assertEqual(self.client.post("/caja/actividad/").status_code, 200)
        self.assertGreater(CashAccessSession.objects.get().last_activity_at, old)
        self.client.post("/caja/bloquear/")
        self.assertEqual(self.client.post("/caja/actividad/", HTTP_ACCEPT="application/json").status_code, 401)

    def test_cashier_opens_without_manager_day(self):
        services.close_business_day(self.day, self.user)
        self.assertEqual(self.page("abrir", True).status_code, 200)
        self.assertFalse(self.cashier.has_perm("cash.open_business_day"))
        session = self.open_cash("500")
        self.assertEqual(session.cashier, self.cashier)
        self.assertEqual(self.page("activa", True).status_code, 200)
        self.assertEqual(session.business_day.status, "OPEN")


    def test_opening_zero_allowed_and_links_correct_station_actor_day(self):
        session = self.open_cash("0")
        self.assertEqual(session.opening_float, Decimal("0"))
        self.assertEqual((session.register_id, session.cashier_id, session.opened_by_id, session.business_day_id), (self.station.pk, self.cashier.pk, self.cashier.pk, self.day.pk))

    def test_invalid_opening_amounts(self):
        for amount in ("-1", "0.001", "NaN", "Infinity", "1e20", "", "abc"):
            with self.subTest(amount=amount):
                response = self.client.post("/caja/accion/abrir/", {"opening_float": amount}, HTTP_ACCEPT="application/json")
                self.assertEqual(response.status_code, 400)
        self.assertFalse(CashSession.objects.exists())

    def test_duplicate_open_and_foreign_station_field_ignored(self):
        other = self.register("PREMIUM", self.other_area)
        response = self.client.post("/caja/accion/abrir/", {"opening_float": "500", "register": other.pk, "cashier": self.other_cashier.pk}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CashSession.objects.get().register, self.station)
        self.assertEqual(self.client.post("/caja/accion/abrir/", {"opening_float": "500"}, HTTP_ACCEPT="application/json").status_code, 409)
        self.assertEqual(CashSession.objects.count(), 1)

    def test_open_permission_required(self):
        self.cashier.user_permissions.remove(Permission.objects.get(codename="open_cash_session"))
        self.assertEqual(self.page("abrir").status_code, 403)
        self.assertEqual(self.client.post("/caja/accion/abrir/", {"opening_float": "500"}, HTTP_ACCEPT="application/json").status_code, 403)

    def test_active_html_and_json_do_not_reveal_financials_even_to_manager(self):
        self.cashier.is_superuser = True; self.cashier.role = "GERENTE"; self.cashier.save()
        self.open_cash()
        for json in (False, True): self.assertPrivate(self.page("activa", json))
        response = self.page("activa")
        self.assertNotContains(response, "Disponible en la siguiente fase")
        self.assertContains(response, "Venta rápida")
        self.assertNotIn("session", response.context)

    def test_only_original_holder_operates_existing_session(self):
        session = self.open_cash()
        self.client.post("/caja/bloquear/")
        self.login(user=self.other_cashier, pin="4632")
        self.assertContains(self.page("activa"), "sesión abierta por Carlos Méndez", status_code=409)
        self.assertEqual(self.post("contar", session, counted_cash="500").status_code, 409)
        self.assertEqual(self.client.post("/caja/accion/abrir/", {"opening_float": "0"}, HTTP_ACCEPT="application/json").status_code, 409)
        session.refresh_from_db(); self.assertEqual(session.cashier, self.cashier)

    def test_handoff_listing_receiving_and_audit(self):
        session = self.open_cash()
        handoff = self.pending()
        response = self.page("meseros")
        self.assertContains(response, "Mesa 01")
        self.assertPrivate(response)
        self.assertEqual(self.post("recibir", session, handoff=handoff.pk).status_code, 200)
        self.assertEqual(self.page("meseros", True).json()["rows"], [])
        movement = CashMovement.objects.get()
        self.assertEqual(movement.created_by, self.cashier)
        self.assertEqual(movement.cash_session, session)
        handoff.refresh_from_db(); self.assertEqual(handoff.received_by, self.cashier)

    def test_duplicate_handoff_human_error(self):
        session = self.open_cash(); handoff = self.pending()
        self.post("recibir", session, handoff=handoff.pk)
        response = self.post("recibir", session, handoff=handoff.pk)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "Este efectivo ya fue recibido en otra caja.")
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_handoff_requires_permission(self):
        session = self.open_cash(); handoff = self.pending()
        self.cashier.user_permissions.remove(Permission.objects.get(codename="receive_waiter_cash"))
        self.assertEqual(self.post("recibir", session, handoff=handoff.pk).status_code, 403)
        self.assertEqual(self.page("meseros").status_code, 403)

    def test_handoff_from_another_day_not_listed_or_received(self):
        session = self.open_cash(); handoff = self.pending()
        old_day = BusinessDay.objects.create(business_date=self.day.business_date - timedelta(days=1), status="CLOSED", opened_by=self.user, closed_by=self.user, closed_at=timezone.now())
        type(handoff.payment.order).objects.filter(pk=handoff.payment.order_id).update(business_day=old_day)
        self.assertEqual(self.page("meseros", True).json()["rows"], [])
        self.assertEqual(self.post("recibir", session, handoff=handoff.pk).status_code, 404)

    def test_malformed_handoff_id_returns_human_error(self):
        self.assertEqual(self.post("recibir", self.open_cash(), handoff="invalid").status_code, 400)

    def test_withdrawal_records_real_requester_approver_and_audit(self):
        session = self.open_cash()
        response = self.withdrawal(session, requested_by=self.other_cashier.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertPrivate(response)
        movement = CashMovement.objects.get()
        self.assertEqual(movement.created_by, self.cashier)
        self.assertEqual(movement.approved_by, self.cashier)
        self.assertEqual(movement.reason, "Cambio")
        log = AuditLog.objects.get(action="cash.withdrawal")
        self.assertEqual(log.data["requested_by"], self.cashier.pk)
        self.assertEqual(CashAccessSession.objects.get().user, self.cashier)

    def test_withdrawal_needs_no_manager_pin_and_ignores_forged_approver(self):
        session = self.open_cash()
        response = self.withdrawal(session, approver_id=self.other_cashier.pk, approver_pin="invalid")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(CashMovement.objects.get().approved_by, self.cashier)
        self.assertTrue(AuditLog.objects.get(action="cash.withdrawal").data["independent"])
        self.assertFalse(CashPinAttempt.objects.filter(user=self.other_cashier).exists())
        self.assertNotContains(self.page("retiro"), 'name="approver_pin"')

    def test_withdrawal_does_not_depend_on_manager_being_active(self):
        self.other_user.is_active = False; self.other_user.save()
        self.assertEqual(self.withdrawal(self.open_cash()).status_code, 200)

    def test_independent_withdrawal_rejects_other_cashier(self):
        from django.core.exceptions import PermissionDenied
        session = self.open_cash()
        with self.assertRaises(PermissionDenied):
            services.create_cash_withdrawal(session, 10, "Cambio", self.other_cashier)
        self.assertFalse(CashMovement.objects.exists())

    def test_requester_needs_withdrawal_permission(self):
        session = self.open_cash()
        token = self.page("retiro", True).json()["withdrawal_token"]
        self.cashier.user_permissions.remove(Permission.objects.get(codename="request_cash_withdrawal"))
        self.assertEqual(self.page("retiro").status_code, 403)
        self.assertEqual(self.post("retirar", session, withdrawal_token=token).status_code, 403)

    def test_withdrawal_validates_amount_reason_and_funds_without_disclosure(self):
        session = self.open_cash()
        for values in ({"amount": "0"}, {"amount": "-1"}, {"amount": "1000"}, {"amount": "0.001"}, {"reason": " "}):
            with self.subTest(values=values):
                response = self.withdrawal(session, **values)
                self.assertEqual(response.status_code, 400)
                self.assertPrivate(response)
        self.assertFalse(CashMovement.objects.exists())

    def test_withdrawal_replay_rejected(self):
        session = self.open_cash()
        token = self.page("retiro", True).json()["withdrawal_token"]
        for expected in (200, 409):
            response = self.post("retirar", session, amount="100", reason="Cambio", approver_id=self.other_user.pk, approver_pin="654321", withdrawal_token=token)
            self.assertEqual(response.status_code, expected)
        self.assertEqual(CashMovement.objects.count(), 1)

    def test_tampered_withdrawal_token_rejected(self):
        self.assertEqual(self.withdrawal(self.open_cash(), withdrawal_token="fake").status_code, 409)

    def test_movements_chronological_reference_and_sign_no_totals(self):
        session = self.open_cash(); handoff = self.pending()
        self.post("recibir", session, handoff=handoff.pk)
        self.withdrawal(session)
        response = self.page("movimientos", True)
        self.assertPrivate(response)
        rows = response.json()["rows"]
        self.assertEqual([r["sign"] for r in rows], ["+", "−"])
        self.assertIn("Mesa 01", rows[0]["reference"])
        self.assertEqual(rows[1]["reference"], "Cambio")
        self.assertPrivate(self.page("movimientos"))

    def test_movement_permission_required(self):
        self.open_cash()
        self.cashier.user_permissions.remove(Permission.objects.get(codename="view_cashmovement"))
        self.assertEqual(self.page("movimientos").status_code, 403)

    def test_blind_page_empty_and_no_disclosure_html_json_or_result_endpoint(self):
        self.open_cash()
        for json in (True, False): self.assertPrivate(self.page("cierre", json))
        self.assertNotContains(self.page("cierre"), 'value="500')
        for screen in ("resultado", "cerrada", "comprobante"):
            response = self.page(screen, True)
            self.assertEqual(response.status_code, 409)
            self.assertPrivate(response)

    def test_blind_count_reveals_result_only_after_submission(self):
        session = self.open_cash()
        response = self.post("contar", session, counted_cash="480")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("expected_cash", response.content.decode())
        result = self.page("resultado", True).json()["result"]
        self.assertEqual(result, {"expected_cash": "500.00", "counted_cash": "480.00", "difference": "-20.00"})
        self.assertContains(self.page("resultado"), "Faltante Q20.00")

    def test_count_cannot_be_modified_and_freezes_new_operations(self):
        session = self.open_cash(); handoff = self.pending()
        token = self.page("retiro", True).json()["withdrawal_token"]
        self.post("contar", session, counted_cash="500")
        for action, data in (("contar", {"counted_cash": "600"}), ("recibir", {"handoff": handoff.pk}), ("retirar", {"withdrawal_token": token})):
            self.assertEqual(self.post(action, session, **data).status_code, 409)
        session.refresh_from_db(); self.assertEqual(session.counted_cash, Decimal("500"))
        self.assertRedirects(self.page("activa"), "/caja/resultado/")
        self.assertFalse(CashMovement.objects.exists())

    def test_count_invalid_and_close_requires_count(self):
        session = self.open_cash()
        for amount in ("-1", "0.001", "NaN", "", "999999999999999"):
            self.assertEqual(self.post("contar", session, counted_cash=amount).status_code, 400)
        self.assertEqual(self.post("cerrar", session).status_code, 400)
        session.refresh_from_db(); self.assertIsNone(session.counted_at)

    def test_shortage_requires_reason_then_closes_immutable(self):
        session = self.open_cash()
        self.post("contar", session, counted_cash="480")
        self.assertEqual(self.post("cerrar", session).status_code, 400)
        self.assertEqual(self.post("cerrar", session, reason="Diferencia en cambio entregado").status_code, 200)
        session.refresh_from_db()
        self.assertEqual(session.status, "CLOSED")
        self.assertEqual(session.closed_by, self.cashier)
        self.assertEqual(session.difference, Decimal("-20"))
        self.assertContains(self.page("cerrada"), "Caja cerrada")
        self.assertContains(self.page("comprobante"), "Diferencia en cambio entregado")
        self.assertEqual(self.post("contar", session, counted_cash="500").status_code, 409)
        self.assertEqual(self.post("retirar", session).status_code, 409)
        self.assertEqual(self.post("recibir", session).status_code, 409)
        self.assertEqual(self.post("cerrar", session, reason="change").status_code, 409)

    def test_surplus_state_and_reason_required(self):
        session = self.open_cash()
        self.post("contar", session, counted_cash="520")
        self.assertContains(self.page("resultado"), "Sobrante Q20.00")
        self.assertEqual(self.post("cerrar", session, reason=" ").status_code, 400)

    def test_balanced_close_requires_no_reason_pending_unassigned_handoff_does_not_block(self):
        session = self.open_cash(); self.pending()
        self.post("contar", session, counted_cash="500")
        self.assertContains(self.page("resultado"), "Caja cuadrada")
        self.assertEqual(self.post("cerrar", session).status_code, 200)
        self.assertEqual(CashHandoff.objects.get().status, "PENDING")

    def test_close_permission_rechecked_for_count_result_and_close(self):
        session = self.open_cash()
        self.cashier.user_permissions.remove(Permission.objects.get(codename="close_cash_session"))
        self.assertEqual(self.post("contar", session, counted_cash="500").status_code, 403)
        services.submit_blind_cash_count(session, "500", self.user)
        self.assertEqual(self.page("resultado").status_code, 403)
        self.assertEqual(self.post("cerrar", session).status_code, 403)

    def test_finish_allows_another_cashier_new_session_and_rejects_old_form(self):
        session = self.open_cash()
        self.post("contar", session, counted_cash="500")
        self.post("cerrar", session)
        self.client.post("/caja/bloquear/")
        self.login(user=self.other_cashier, pin="4632")
        new = self.open_cash("10")
        self.assertEqual(new.cashier, self.other_cashier)
        self.assertNotEqual(new.pk, session.pk)
        self.assertEqual(self.post("contar", session, counted_cash="500").status_code, 409)

    def test_foreign_session_id_cannot_mutate(self):
        self.open_cash()
        other = services.open_cash_session(self.register("PREMIUM", self.other_area), self.other_cashier, "100", self.other_cashier)
        self.assertEqual(self.post("contar", other, counted_cash="100").status_code, 409)
        other.refresh_from_db(); self.assertIsNone(other.counted_at)

    def test_closed_day_revokes_access_before_mutation(self):
        session = self.open_cash()
        BusinessDay.objects.filter(pk=self.day.pk).update(status="CLOSED", closed_at=timezone.now(), closed_by=self.user)
        self.assertEqual(self.post("contar", session, counted_cash="500").status_code, 401)
        session.refresh_from_db(); self.assertIsNone(session.counted_at)

    def test_mutations_post_only(self):
        for path in ("accion/abrir", "accion/recibir", "accion/retirar", "accion/contar", "accion/cerrar", "bloquear", "actividad"):
            self.assertEqual(self.client.get(f"/caja/{path}/").status_code, 405)

    def test_csrf_required_for_every_mutation(self):
        client = Client(enforce_csrf_checks=True)
        client.cookies.update(self.client.cookies)
        for path in ("configurar", "acceso", "accion/abrir", "accion/recibir", "accion/retirar", "accion/contar", "accion/cerrar", "bloquear", "actividad"):
            self.assertEqual(client.post(f"/caja/{path}/", {}).status_code, 403)

    def test_no_secrets_in_audit_or_html(self):
        self.login(pin="1111")
        self.open_cash()
        self.withdrawal(CashSession.objects.get(), approver_pin="1234")
        for log in AuditLog.objects.all():
            self.assertNotIn("654321", str(log.data))
            self.assertNotIn("1234", str(log.data))
        self.assertNotContains(self.page("retiro"), "654321")
