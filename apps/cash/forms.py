from decimal import Decimal

from django import forms
from django.contrib.auth import get_user_model

from .models import CashRegister, CashSession, CashHandoff, BusinessDay


class SessionSelectionForm(forms.Form):
    session = forms.ModelChoiceField(label="Sesión", queryset=CashSession.objects.all(), required=False)


class OpenSessionForm(forms.Form):
    register = forms.ModelChoiceField(label="Estación", queryset=CashRegister.objects.filter(is_active=True))
    cashier = forms.ModelChoiceField(label="Cajero", queryset=get_user_model().objects.filter(is_active=True))
    opening_float = forms.DecimalField(label="Fondo inicial (Q)", decimal_places=2, max_digits=14, min_value=Decimal("0"))


class SessionActionForm(forms.Form):
    session = forms.ModelChoiceField(label="Sesión", queryset=CashSession.objects.filter(status="OPEN"))


class HandoffForm(SessionActionForm):
    handoff = forms.ModelChoiceField(label="Efectivo pendiente", queryset=CashHandoff.objects.filter(status="PENDING"))


class WithdrawalForm(SessionActionForm):
    amount = forms.DecimalField(label="Retiro (Q)", decimal_places=2, max_digits=14, min_value=Decimal("0.01"))
    reason = forms.CharField(label="Motivo")
    requested_by = forms.ModelChoiceField(label="Solicitante", queryset=get_user_model().objects.filter(is_active=True))


class CountForm(SessionActionForm):
    counted_cash = forms.DecimalField(label="Efectivo contado físicamente (Q)", decimal_places=2, max_digits=14, min_value=Decimal("0"))


class CloseSessionForm(SessionActionForm):
    reason = forms.CharField(label="Motivo de diferencia", required=False)


class DaySelectionForm(forms.Form):
    day = forms.ModelChoiceField(label="Jornada", queryset=BusinessDay.objects.all(), required=False)


class OpenDayForm(forms.Form):
    business_date = forms.DateField(label="Fecha comercial", widget=forms.DateInput(attrs={"type": "date"}))


class DayActionForm(forms.Form):
    day = forms.ModelChoiceField(label="Jornada", queryset=BusinessDay.objects.all())
    reason = forms.CharField(label="Motivo (obligatorio al reabrir)", required=False)
