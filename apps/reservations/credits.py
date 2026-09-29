from decimal import Decimal
from django.core.exceptions import ValidationError
from .models import ReservationCreditAllocation
from .services import log

ZERO = Decimal('0.00')


def credits_for(order):
    if hasattr(order, '_reservation_credits'):
        return order._reservation_credits
    return order.reservation_credits.select_related('payment__reservation').prefetch_related('allocations__order_line').all()


def credit_summary(order):
    credits = list(credits_for(order))
    amount = sum((c.amount for c in credits), ZERO)
    applied = sum((a.amount for c in credits for a in c.allocations.all()), ZERO)
    return {'amount': amount, 'applied': applied, 'remaining': amount - applied,
            'codes': [c.payment.reservation.public_code for c in credits]}


def assert_credit_integrity(order):
    for credit in credits_for(order):
        reservation = credit.payment.reservation
        rows = list(credit.allocations.all())
        if (credit.payment.status != 'CONFIRMED' or reservation.payment_application != 'CREDIT' or
                reservation.order_id != order.pk or credit.amount != credit.payment.amount or
                sum((r.amount for r in rows), ZERO) > credit.amount):
            raise ValidationError('Crédito de reserva inconsistente.')
        for row in rows:
            if row.order_line.order_id != order.pk or row.order_line.status != 'SENT' or not 1 <= row.unit_number <= row.order_line.quantity:
                raise ValidationError('Asignación de anticipo fuera del consumo autorizado.')


def apply_available_credit(order, user):
    """Llamado al enviar consumo bajo bloqueo de jornada/cuenta; nunca sobre borradores."""
    from apps.payments.queries import unit_ledger
    for credit in credits_for(order):
        remaining = credit.amount - sum((a.amount for a in credit.allocations.all()), ZERO)
        applied = ZERO
        for unit in unit_ledger(order).values():
            value = min(remaining, max(ZERO, unit['available']))
            if value:
                row, created = ReservationCreditAllocation.objects.get_or_create(credit=credit, order_line=unit['line'],
                    unit_number=unit['unit_number'], defaults={'amount': value})
                # Una asignación previa solo se amplía cuando la unidad aún tiene saldo.
                if not created:
                    row.amount += value
                    row.save(update_fields=['amount'])
                remaining -= value
                applied += value
            if not remaining:
                break
        if applied:
            log(credit.payment.reservation, 'credit_applied', user, order_id=order.pk, amount=str(applied), credit_id=credit.pk)
