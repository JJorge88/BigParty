from django import forms

from apps.catalog.models import Product

from .models import InventoryMovement


class InventoryMovementForm(forms.Form):
    product = forms.ModelChoiceField(label="Producto", queryset=Product.objects.filter(track_inventory=True, is_combo=False))
    movement_type = forms.ChoiceField(label="Movimiento", choices=())
    quantity_delta = forms.IntegerField(label="Cantidad o variación", help_text="Entrada: entero positivo. Ajuste: entero positivo o negativo.")
    reason = forms.CharField(label="Motivo", required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        choices = []
        if user.has_perm("inventory.receive_inventory"):
            choices.append((InventoryMovement.MovementType.RECEIPT, "Entrada"))
        if user.has_perm("inventory.adjust_inventory"):
            choices.append((InventoryMovement.MovementType.ADJUSTMENT, "Ajuste"))
        self.fields["movement_type"].choices = choices

    def clean(self):
        cleaned = super().clean()
        quantity = cleaned.get("quantity_delta")
        movement_type = cleaned.get("movement_type")
        if quantity == 0:
            self.add_error("quantity_delta", "La cantidad no puede ser cero.")
        if movement_type == InventoryMovement.MovementType.RECEIPT and quantity is not None and quantity < 0:
            self.add_error("quantity_delta", "La entrada debe ser positiva.")
        if movement_type == InventoryMovement.MovementType.ADJUSTMENT and not cleaned.get("reason"):
            self.add_error("reason", "Indica el motivo del ajuste.")
        return cleaned
