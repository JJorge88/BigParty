from importlib import reload
from decimal import Decimal as D

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import override_settings, Client, RequestFactory
from django.urls import clear_url_caches, resolve, Resolver404
from django.http import Http404

from apps.cash import services as s
from apps.cash.models import CashRegister, CashSession, CashMovement, CashHandoff, BusinessDay, BusinessDayReopen
from apps.cash.views import CashDevelopmentView, BusinessDayDevelopmentView
from apps.payments.models import Payment
from .base import CashTestCase


@override_settings(DEBUG=True, ROOT_URLCONF="config.urls")
class CashAdminViewTests(CashTestCase):
    def setUp(self):
        import config.urls
        reload(config.urls)
        clear_url_caches()
        self.client.force_login(self.user)

    def tearDown(self):
        import config.urls
        with override_settings(DEBUG=False):
            reload(config.urls)
        clear_url_caches()

    def grant(self, user, *permissions):
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="cash", codename__in=permissions))
        return get_user_model().objects.get(pk=user.pk)

    def test_financial_admin_is_readonly_and_register_controlled(self):
        request = RequestFactory().get("/admin/")
        request.user = self.user
        for model in (CashSession, CashMovement, CashHandoff, BusinessDay, BusinessDayReopen):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))
        self.assertTrue(admin.site._registry[CashRegister].has_change_permission(request))
        self.assertFalse(admin.site._registry[CashRegister].has_delete_permission(request))

    def test_native_view_session_permission_does_not_reveal_financial_admin(self):
        user = get_user_model().objects.create_user(username="cash-view", is_staff=True)
        user = self.grant(user, "view_cashsession", "view_cashmovement", "view_cashhandoff")
        request = RequestFactory().get("/admin/"); request.user = user
        for model in (CashSession, CashMovement, CashHandoff):
            self.assertFalse(admin.site._registry[model].has_view_permission(request))

    def test_cash_view_never_reveals_expected_before_count_even_to_superuser(self):
        session = self.session("483.17")
        order, _ = self.consumption()
        self.payment(order, session=session)
        response = self.client.get("/dev/caja/", {"session": session.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "508.17")
        self.assertNotContains(response, "508,17")
        self.assertNotContains(response, "Efectivo esperado:")
        self.assertNotIn("result", response.context)
        self.assertNotIn("summary", response.context)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "count", "session": session.pk, "counted_cash": "500.00"}).status_code, 302)
        response = self.client.get("/dev/caja/", {"session": session.pk})
        self.assertContains(response, "Efectivo esperado:")
        self.assertEqual(response.context["result"]["difference"], D("-8.17"))
        self.assertEqual(self.client.post("/dev/caja/", {"action": "close", "session": session.pk}).status_code, 400)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "close", "session": session.pk, "reason": "Faltante investigado"}).status_code, 302)

    def test_open_handoff_withdraw_count_close_dev_flow(self):
        register = self.register()
        response = self.client.post("/dev/caja/", {"action": "open", "register": register.pk, "cashier": self.user.pk, "opening_float": "100"})
        self.assertEqual(response.status_code, 302)
        session = CashSession.objects.get()
        order, _ = self.consumption()
        payment = self.payment(order)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "handoff", "session": session.pk, "handoff": payment.cash_handoff.pk}).status_code, 302)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "withdraw", "session": session.pk, "amount": "25", "reason": "Bóveda", "requested_by": self.other_user.pk, "approved_by": self.other_user.pk}).status_code, 302)
        movement = CashMovement.objects.get(movement_type="WITHDRAWAL")
        self.assertEqual(movement.approved_by, self.user)
        self.assertEqual(movement.created_by, self.other_user)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "count", "session": session.pk, "counted_cash": "100"}).status_code, 302)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "close", "session": session.pk}).status_code, 302)

    def test_payment_dev_accepts_explicit_cash_session(self):
        session = self.session()
        order, _ = self.consumption(1)
        response = self.client.post("/dev/pagos/", {"action": "pay", "order": order.pk, "mode": "full", "method": "CASH", "cash_session": session.pk})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Payment.objects.get().cash_handoff_status, "NOT_REQUIRED")
        self.assertEqual(s.get_expected_cash(session), D("125"))

    def test_day_view_blockers_summary_close_and_reopen(self):
        response = self.client.get("/dev/jornada/", {"day": self.day.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["blockers"], [])
        self.assertEqual(response.context["summary"]["gross_sales"], D("0"))
        self.assertEqual(self.client.post("/dev/jornada/", {"action": "close", "day": self.day.pk}).status_code, 302)
        self.assertEqual(self.client.post("/dev/jornada/", {"action": "reopen", "day": self.day.pk}).status_code, 400)
        self.assertEqual(self.client.post("/dev/jornada/", {"action": "reopen", "day": self.day.pk, "reason": "Corrección"}).status_code, 302)
        self.assertEqual(BusinessDayReopen.objects.count(), 1)

    def test_day_open_dev_uses_explicit_commercial_date(self):
        s.close_business_day(self.day, self.user)
        response = self.client.post("/dev/jornada/", {"action": "open", "business_date": "2030-01-01"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(str(BusinessDay.objects.get(status="OPEN").business_date), "2030-01-01")

    def test_day_summary_and_blockers_are_not_shown_to_view_only_user(self):
        self.consumption()
        user = get_user_model().objects.create_user(username="view-day-only", is_staff=True)
        self.grant(user, "view_businessday")
        self.client.force_login(user)
        response = self.client.get("/dev/jornada/", {"day": self.day.pk})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("summary", response.context)
        self.assertNotIn("blockers", response.context)
        self.assertEqual(self.client.post("/dev/jornada/", {"action": "close", "day": self.day.pk}).status_code, 403)

    def test_login_staff_permissions_and_csrf_required(self):
        self.client.logout()
        for url in ("/dev/caja/", "/dev/jornada/"):
            self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user(username="unprivileged", is_staff=True)
        self.client.force_login(user)
        for url in ("/dev/caja/", "/dev/jornada/"):
            self.assertEqual(self.client.get(url).status_code, 403)
        self.grant(user, "view_cashsession")
        self.assertEqual(self.client.get("/dev/caja/").status_code, 200)
        self.assertEqual(self.client.post("/dev/caja/", {"action": "count"}).status_code, 403)
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        for url in ("/dev/caja/", "/dev/jornada/"):
            self.assertEqual(client.post(url, {"action": "open"}).status_code, 403)

    def test_debug_false_removes_both_routes_and_guards_views(self):
        import config.urls
        with override_settings(DEBUG=False):
            reload(config.urls)
            clear_url_caches()
            for url, view in (("/dev/caja/", CashDevelopmentView), ("/dev/jornada/", BusinessDayDevelopmentView)):
                with self.assertRaises(Resolver404):
                    resolve(url)
                request = RequestFactory().get(url); request.user = self.user
                with self.assertRaises(Http404):
                    view.as_view()(request)
