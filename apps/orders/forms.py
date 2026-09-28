from django import forms
from django.contrib.auth import get_user_model

from apps.catalog.models import Product, ModifierOption
from apps.tables.models import VenueTable

from .models import ACTIVE_STATUSES, TableOrder, SubAccount


class OpenOrderForm(forms.Form):
    table = forms.ModelChoiceField(label="Mesa", queryset=VenueTable.objects.filter(is_active=True, operational_status="ACTIVE"))
    responsible_waiter = forms.ModelChoiceField(label="Responsable", queryset=get_user_model().objects.filter(is_active=True), required=False)
    billing_mode = forms.ChoiceField(label="Modalidad", choices=TableOrder.BillingMode.choices)
    general_note = forms.CharField(label="Nota general", required=False)


class OrderSelectionForm(forms.Form):
    order = forms.ModelChoiceField(label="Consultar cuenta", queryset=TableOrder.objects.all(), required=False)


class OrderActionForm(forms.Form):
    order = forms.ModelChoiceField(label="Cuenta", queryset=TableOrder.objects.filter(status__in=ACTIVE_STATUSES))


class SubAccountForm(OrderActionForm):
    name = forms.CharField(label="Nombre de subcuenta", max_length=100)


class AddProductForm(OrderActionForm):
    product = forms.ModelChoiceField(label="Producto", queryset=Product.objects.filter(is_active=True, visible_in_pos=True))
    quantity = forms.IntegerField(label="Cantidad", min_value=1, initial=1)
    subaccount = forms.ModelChoiceField(label="Subcuenta (opcional)", queryset=SubAccount.objects.filter(status="OPEN"), required=False)
    modifiers = forms.ModelMultipleChoiceField(label="Modificadores", queryset=ModifierOption.objects.filter(is_active=True, group__is_active=True), required=False)
    notes = forms.CharField(label="Nota del producto", required=False)
