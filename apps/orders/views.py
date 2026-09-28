from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.mixins import StaffDebugPermissionMixin

from .forms import OpenOrderForm, OrderSelectionForm, OrderActionForm, SubAccountForm, AddProductForm
from .models import ACTIVE_STATUSES
from .services import (open_table_order, create_subaccount, add_product_to_order, send_order,
                       get_order_timeline, get_order_committed_total, get_order_pending_total, get_order_tickets)


class OrdersDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    template_name = "orders/development.html"
    permission_required = "orders.view_tableorder"
    forms = {"open": OpenOrderForm, "subaccount": SubAccountForm, "add": AddProductForm, "send": OrderActionForm}
    action_permissions = {"open": "open_table_order", "subaccount": "manage_subaccounts", "add": "add_order_line", "send": "send_order"}
    action_labels = {"open": "Abrir mesa", "subaccount": "Crear subcuenta", "add": "Agregar producto", "send": "Enviar pedido"}

    def context(self, selected=None, selection=None, bound_action=None, bound_form=None):
        operations = []
        for action, form_class in self.forms.items():
            if self.request.user.has_perm("orders." + self.action_permissions[action]):
                if selected and selected.status not in ACTIVE_STATUSES and action != "open":
                    continue
                form = bound_form if action == bound_action else form_class(initial={"order": selected})
                operations.append((action, self.action_labels[action], form))
        context = {"operations": operations, "selected": selected, "selection": selection or OrderSelectionForm()}
        if selected:
            context.update(lines=selected.lines.select_related("subaccount"),
                           timeline=get_order_timeline(selected), tickets=get_order_tickets(selected),
                           pending=get_order_pending_total(selected), committed=get_order_committed_total(selected))
        return context

    def get(self, request, *args, **kwargs):
        selection = OrderSelectionForm(request.GET)
        valid = selection.is_valid()
        return self.render_to_response(self.context(selection.cleaned_data.get("order") if valid else None, selection), status=200 if valid else 400)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action not in self.forms:
            return self.render_to_response(self.context(), status=400)
        form = self.forms[action](request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if action == "open":
                    order = open_table_order(data["table"], request.user, responsible_waiter=data["responsible_waiter"],
                                             billing_mode=data["billing_mode"], general_note=data["general_note"])
                else:
                    order = data["order"]
                    if action == "subaccount":
                        create_subaccount(order, data["name"], request.user)
                    elif action == "add":
                        add_product_to_order(order, data["product"], data["quantity"], request.user,
                            subaccount=data["subaccount"], modifier_option_ids=list(data["modifiers"].values_list("pk", flat=True)), notes=data["notes"])
                    else:
                        send_order(order, request.user)
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                messages.success(request, "Operación registrada correctamente.")
                return redirect(reverse("orders:development") + f"?order={order.pk}")
        return self.render_to_response(self.context(bound_action=action, bound_form=form), status=400)
