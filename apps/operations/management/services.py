"""Confirmaciones de interfaz: permisos y alcance; el dominio ejecuta las operaciones."""
from django.db import transaction
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404
from apps.cash.guards import lock_operation_gate
from apps.cash.models import BusinessDay
from apps.cash import services as cash
from apps.payments.models import Payment
from apps.payments import services as payments
from . import security


def payment_revision(payment, day):
    return f'{day.updated_at.isoformat()}|{payment.pk}|{payment.order_id}|{payment.status}|{payment.amount}|{payment.reference}'


@transaction.atomic
def day_action(request, action, day_id=None, business_date=None):
    permissions = {'open':'open_business_day','close':'close_business_day','reopen':'reopen_business_day'}
    security.require(request.user,'cash.'+permissions[action])
    lock_operation_gate()
    if action == 'open':
        security.verify_confirmation(request,'open',0,'new-day')
        return cash.open_business_day(request.user,business_date)
    day = get_object_or_404(BusinessDay.objects.select_for_update(),pk=day_id)
    security.verify_confirmation(request,action,day.pk,day.updated_at.isoformat())
    if action == 'close':
        # El servicio vuelve a consultar blockers bajo la barrera transaccional de jornada.
        return cash.close_business_day(day,request.user)
    reason = request.POST.get('reason','').strip()
    if not reason:
        raise ValidationError('El motivo de reapertura es obligatorio.')
    return cash.reopen_business_day(day,request.user,reason)


@transaction.atomic
def review_payment(request, day_id, payment_id, action):
    permission = {'confirm':'verify_transfer_payment','reject':'reject_transfer_payment'}.get(action)
    if permission is None:
        raise ValidationError('Selecciona confirmar o rechazar el pago.')
    security.require(request.user,'payments.'+permission)
    lock_operation_gate()
    day = get_object_or_404(BusinessDay.objects.select_for_update(),pk=day_id)
    payment = get_object_or_404(Payment.objects.select_for_update(),pk=payment_id,order__business_day=day,
                                method__in=['TRANSFER','DEPOSIT'])
    if day.status != 'OPEN':
        raise ValidationError('La jornada está cerrada. Requiere reapertura autorizada antes de corregir pagos.')
    security.verify_confirmation(request,action,payment.pk,payment_revision(payment,day))
    if action == 'confirm':
        return payments.confirm_pending_payment(payment,request.user)
    return payments.reject_pending_payment(payment,request.user,request.POST.get('reason',''))
