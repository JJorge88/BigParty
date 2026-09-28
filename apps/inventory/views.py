from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.catalog.models import Product
from apps.core.mixins import StaffDebugPermissionMixin

from .forms import InventoryMovementForm
from .models import InventoryMovement
from .services import adjust_stock, receive_stock


class InventoryDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    template_name = "inventory/development.html"
    permission_required = "inventory.view_inventory"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("form", InventoryMovementForm(user=self.request.user))
        context["can_move"] = bool(context["form"].fields["movement_type"].choices)
        # Los combos no tienen existencias propias: se consultan en catálogo.
        context["products"] = Product.objects.filter(is_combo=False).select_related("category")
        return context

    def post(self, request, *args, **kwargs):
        movement_type = request.POST.get("movement_type")
        permission = {
            InventoryMovement.MovementType.RECEIPT: "inventory.receive_inventory",
            InventoryMovement.MovementType.ADJUSTMENT: "inventory.adjust_inventory",
        }.get(movement_type)
        if permission and not request.user.has_perm(permission):
            raise PermissionDenied
        form = InventoryMovementForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if data["movement_type"] == InventoryMovement.MovementType.RECEIPT:
                    receive_stock(data["product"], data["quantity_delta"], user=request.user, reason=data["reason"])
                else:
                    adjust_stock(data["product"], data["quantity_delta"], user=request.user, reason=data["reason"])
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                messages.success(request, "Movimiento registrado correctamente.")
                return redirect("inventory:development")
        return self.render_to_response(self.get_context_data(form=form), status=400)
