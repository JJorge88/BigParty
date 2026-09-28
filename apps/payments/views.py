from django.contrib import messages
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.mixins import StaffDebugPermissionMixin
from apps.orders.forms import OrderSelectionForm
from .forms import PaymentForm, PendingPaymentForm, CloseOrderForm
from . import services as s


class PaymentsDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    template_name = "payments/development.html"
    permission_required = "payments.view_payment"
    actions = {"pay": (PaymentForm, "record_payment", "Registrar pago"),
               "confirm": (PendingPaymentForm, "verify_transfer_payment", "Confirmar transferencia/depósito"),
               "reject": (PendingPaymentForm, "reject_transfer_payment", "Rechazar transferencia/depósito"),
               "close": (CloseOrderForm, "close_order", "Cerrar cuenta")}

    def context(self, selected=None, selection=None, bound_action=None, bound_form=None):
        operations = [(key, label, bound_form if key == bound_action else cls(initial={"order": selected}))
                      for key, (cls, permission, label) in self.actions.items()
                      if self.request.user.has_perm("payments." + permission)]
        data = {"selected": selected, "selection": selection or OrderSelectionForm(), "operations": operations}
        if selected:
            data.update(summary=s.get_financial_summary(selected), history=s.get_payment_history(selected),
                        lines=selected.lines.filter(status="SENT"),
                        subaccounts=[(a, s.get_financial_summary(a)) for a in selected.subaccounts.all()],
                        can_close=s.can_close_order(selected))
        return data

    def get(self, request, *args, **kwargs):
        selection = OrderSelectionForm(request.GET)
        valid = selection.is_valid()
        return self.render_to_response(self.context(selection.cleaned_data.get("order") if valid else None, selection), status=200 if valid else 400)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action not in self.actions:
            return self.render_to_response(self.context(), status=400)
        form_class, permission, _ = self.actions[action]
        if not request.user.has_perm("payments." + permission):
            raise PermissionDenied
        form = form_class(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if action == "pay":
                    target = data["subaccount"] or data["order"]
                    options = {key: data[key] for key in ("reference", "received_amount", "card_approved", "notes", "cash_session")}
                    if data["mode"] == "full":
                        payment = s.pay_full_balance(target, data["method"], request.user, **options)
                    elif data["mode"] == "amount":
                        payment = s.create_amount_payment(target, data["amount"], data["method"], request.user, **options)
                    else:
                        payment = s.create_selected_payment(target, data["selection"], data["method"], request.user, **options)
                    order = payment.order
                    messages.success(request, f"Pago Q{payment.amount} registrado. Cambio: Q{payment.change_due}.")
                elif action == "close":
                    order = s.close_order(data["order"], request.user)
                    messages.success(request, "Cuenta cerrada y mesas liberadas.")
                else:
                    payment = (s.confirm_pending_payment(data["payment"], request.user) if action == "confirm"
                               else s.reject_pending_payment(data["payment"], request.user, data["reason"]))
                    order = payment.order
                    messages.success(request, "Verificación registrada.")
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                return redirect(reverse("payments:development") + f"?order={order.pk}")
        return self.render_to_response(self.context(bound_action=action, bound_form=form), status=400)
