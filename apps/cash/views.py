from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.mixins import StaffDebugPermissionMixin
from . import services as s
from .forms import (SessionSelectionForm, OpenSessionForm, HandoffForm, WithdrawalForm, CountForm,
                    CloseSessionForm, DaySelectionForm, OpenDayForm, DayActionForm)


class CashDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    permission_required = "cash.view_cashsession"
    template_name = "cash/development.html"
    actions = {"open": (OpenSessionForm, "open_cash_session", "Abrir caja"),
               "handoff": (HandoffForm, "receive_waiter_cash", "Confirmar entrega"),
               "withdraw": (WithdrawalForm, "approve_cash_withdrawal", "Aprobar retiro"),
               "count": (CountForm, "close_cash_session", "Enviar conteo ciego"),
               "close": (CloseSessionForm, "close_cash_session", "Cerrar sesión")}

    def context(self, selected=None, selection=None, bound_action=None, bound_form=None):
        data = {"selection": selection or SessionSelectionForm(), "selected": selected,
                "operations": [(key, label, bound_form if key == bound_action else cls(initial={"session": selected}))
                    for key, (cls, perm, label) in self.actions.items() if self.request.user.has_perm("cash." + perm)]}
        if self.request.user.has_perm("cash.receive_waiter_cash"):
            data["handoffs"] = s.get_pending_cash_handoffs()
        # Nunca se llama al resumen financiero ni al esperado antes de presentar el conteo.
        if selected and selected.counted_at and self.request.user.has_perm("cash.close_cash_session"):
            data["result"] = s.get_blind_close_result(selected, self.request.user)
        return data

    def get(self, request, *args, **kwargs):
        form = SessionSelectionForm(request.GET)
        valid = form.is_valid()
        return self.render_to_response(self.context(form.cleaned_data.get("session") if valid else None, form), status=200 if valid else 400)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action not in self.actions:
            return self.render_to_response(self.context(), status=400)
        cls, permission, _ = self.actions[action]
        if not request.user.has_perm("cash." + permission):
            raise PermissionDenied
        form = cls(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if action == "open":
                    session = s.open_cash_session(data["register"], data["cashier"], data["opening_float"], request.user)
                else:
                    session = data["session"]
                    if action == "handoff":
                        s.confirm_cash_handoff(data["handoff"], session, request.user)
                    elif action == "withdraw":
                        # El aprobador es siempre el usuario autenticado, nunca un ID del formulario.
                        s.create_cash_withdrawal(session, data["amount"], data["reason"], data["requested_by"], request.user)
                    elif action == "count":
                        s.submit_blind_cash_count(session, data["counted_cash"], request.user)
                    else:
                        s.close_cash_session(session, request.user, data["reason"])
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                messages.success(request, "Operación registrada.")
                return redirect(reverse("cash:development") + f"?session={session.pk}")
        return self.render_to_response(self.context(bound_action=action, bound_form=form), status=400)


class BusinessDayDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    permission_required = "cash.view_businessday"
    template_name = "cash/business_day.html"
    actions = {"open": (OpenDayForm, "open_business_day", "Abrir jornada"),
               "close": (DayActionForm, "close_business_day", "Cerrar jornada"),
               "reopen": (DayActionForm, "reopen_business_day", "Reabrir jornada")}

    def context(self, selected=None, selection=None, bound_action=None, bound_form=None):
        data = {"selection": selection or DaySelectionForm(), "selected": selected,
                "operations": [(key, label, bound_form if key == bound_action else cls(initial={"day": selected}))
                    for key, (cls, perm, label) in self.actions.items() if self.request.user.has_perm("cash." + perm)]}
        if selected and self.request.user.has_perm("cash.close_business_day"):
            data["blockers"] = s.get_business_day_close_blockers(selected)
        if selected and self.request.user.has_perm("cash.view_cash_session_financials"):
            data["summary"] = s.get_business_day_summary(selected)
        return data

    def get(self, request, *args, **kwargs):
        form = DaySelectionForm(request.GET)
        valid = form.is_valid()
        return self.render_to_response(self.context(form.cleaned_data.get("day") if valid else None, form), status=200 if valid else 400)

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action not in self.actions:
            return self.render_to_response(self.context(), status=400)
        cls, permission, _ = self.actions[action]
        if not request.user.has_perm("cash." + permission):
            raise PermissionDenied
        form = cls(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            try:
                if action == "open":
                    day = s.open_business_day(request.user, data["business_date"])
                elif action == "close":
                    day = s.close_business_day(data["day"], request.user)
                else:
                    day = s.reopen_business_day(data["day"], request.user, data["reason"])
            except ValidationError as exc:
                form.add_error(None, " ".join(exc.messages))
            else:
                messages.success(request, "Operación de jornada registrada.")
                return redirect(reverse("cash:business-day") + f"?day={day.pk}")
        return self.render_to_response(self.context(bound_action=action, bound_form=form), status=400)
