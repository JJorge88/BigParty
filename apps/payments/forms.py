from decimal import Decimal

from django import forms

from apps.orders.models import TableOrder, SubAccount, ACTIVE_STATUSES
from .models import Payment


class PaymentForm(forms.Form):
    order = forms.ModelChoiceField(label="Cuenta", queryset=TableOrder.objects.filter(status__in=ACTIVE_STATUSES))
    subaccount = forms.ModelChoiceField(label="Subcuenta opcional", queryset=SubAccount.objects.filter(status="OPEN"), required=False)
    mode = forms.ChoiceField(label="Aplicar a", choices=[("full", "Saldo disponible completo"), ("amount", "Monto parcial"), ("selected", "Artículos seleccionados")])
    amount = forms.DecimalField(label="Monto parcial (Q)", max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False)
    selection = forms.JSONField(label="Selección de artículos", required=False, help_text='Ejemplo: [{"line_id": 10, "quantity": 2}]')
    method = forms.ChoiceField(label="Método", choices=Payment.Method.choices)
    reference = forms.CharField(label="Referencia de transferencia/depósito", max_length=200, required=False)
    received_amount = forms.DecimalField(label="Efectivo recibido (opcional)", max_digits=14, decimal_places=2, min_value=Decimal("0.01"), required=False)
    card_approved = forms.BooleanField(label="La terminal bancaria aprobó el cobro con tarjeta", required=False)
    notes = forms.CharField(label="Notas", required=False)

    def clean(self):
        data = super().clean()
        account, order = data.get("subaccount"), data.get("order")
        if account and order and account.order_id != order.pk:
            raise forms.ValidationError("La subcuenta no pertenece a la cuenta seleccionada.")
        if data.get("mode") == "amount" and data.get("amount") is None:
            self.add_error("amount", "Indica el monto parcial.")
        if data.get("mode") == "selected" and not data.get("selection"):
            self.add_error("selection", "Indica líneas y cantidades.")
        return data


class PendingPaymentForm(forms.Form):
    payment = forms.ModelChoiceField(label="Pago pendiente", queryset=Payment.objects.filter(status="PENDING"))
    reason = forms.CharField(label="Motivo (obligatorio al rechazar)", required=False)


class CloseOrderForm(forms.Form):
    order = forms.ModelChoiceField(label="Cuenta a cerrar", queryset=TableOrder.objects.filter(status__in=ACTIVE_STATUSES))
