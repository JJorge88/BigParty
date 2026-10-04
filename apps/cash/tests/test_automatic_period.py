from datetime import timedelta
from unittest.mock import patch
from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from apps.cash import services
from apps.cash.models import BusinessDay
from .base import CashTestCase


class AutomaticCashPeriodTests(CashTestCase):
    def cashier(self):
        user = get_user_model().objects.create_user(username='independent-cashier', role='CAJERO')
        user.user_permissions.add(Permission.objects.get(codename='open_cash_session'))
        return user

    def test_first_register_creates_period_without_manager_permission(self):
        self.day.delete()
        cashier = self.cashier()
        session = services.open_cash_session(self.register(), cashier, 10, cashier)
        self.assertEqual(session.business_day.opened_by, cashier)
        self.assertEqual(BusinessDay.objects.filter(status='OPEN').count(), 1)

    def test_invalid_opening_rolls_back_automatic_period(self):
        self.day.delete()
        cashier = self.cashier()
        with self.assertRaises(ValidationError):
            services.open_cash_session(self.register(), cashier, -1, cashier)
        self.assertFalse(BusinessDay.objects.exists())

    def test_new_date_rotates_only_settled_period(self):
        cashier = self.cashier()
        with patch('apps.cash.services.timezone.localdate', return_value=self.day.business_date + timedelta(days=1)):
            session = services.open_cash_session(self.register(), cashier, 0, cashier)
        self.day.refresh_from_db()
        self.assertEqual(self.day.status, 'CLOSED')
        self.assertNotEqual(session.business_day_id, self.day.pk)

    def test_open_register_keeps_overnight_operations_together(self):
        first = self.session()
        cashier = self.cashier()
        with patch('apps.cash.services.timezone.localdate', return_value=self.day.business_date + timedelta(days=1)):
            second = services.open_cash_session(self.register('SECOND'), cashier, 0, cashier)
        self.assertEqual(first.business_day_id, second.business_day_id)
        self.assertEqual(BusinessDay.objects.filter(status='OPEN').count(), 1)

    def test_multiple_shifts_keep_closed_cash_session_unchanged(self):
        first = self.session()
        self.close_session(first)
        cashier = self.cashier()
        second = services.open_cash_session(first.register, cashier, 20, cashier)
        first.refresh_from_db()
        self.assertEqual(first.status, 'CLOSED')
        self.assertNotEqual(first.pk, second.pk)
