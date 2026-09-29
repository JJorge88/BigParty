"""Configuración administrativa mínima; los secretos permanecen en el entorno."""
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from apps.payments.models import Payment


class BusinessSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    business_name = models.CharField('nombre del negocio', max_length=100, default='BIG PARTY')
    timezone = models.CharField('zona horaria', max_length=64, default='America/Guatemala', editable=False)
    currency_code = models.CharField('moneda', max_length=3, default='GTQ', editable=False)
    currency_symbol = models.CharField('símbolo', max_length=4, default='Q', editable=False)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name='business_settings_singleton')]
        permissions = [('view_reports', 'Puede consultar reportes financieros'),
                       ('export_reports_pdf', 'Puede exportar reportes PDF'),
                       ('view_configuration', 'Puede consultar configuración'),
                       ('change_business_configuration', 'Puede configurar el negocio'),
                       ('change_payment_method_configuration', 'Puede configurar métodos de pago'),
                       ('change_bank_transfer_configuration', 'Puede configurar datos de transferencia')]


class PaymentMethodSettings(models.Model):
    method = models.CharField('método', max_length=10, choices=Payment.Method.choices, primary_key=True)
    enabled = models.BooleanField('habilitado', default=True)
    display_order = models.PositiveSmallIntegerField('orden', default=0)

    class Meta:
        ordering = ('display_order', 'method')
        constraints = [models.CheckConstraint(condition=Q(method__in=Payment.Method.values), name='known_payment_method')]


class BankTransferSettings(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    enabled = models.BooleanField('publicar datos de transferencia', default=False)
    bank_name = models.CharField('banco', max_length=100, blank=True)
    account_name = models.CharField('titular', max_length=150, blank=True)
    account_number = models.CharField('número de cuenta', max_length=60, blank=True)
    instructions = models.TextField('instrucciones adicionales', blank=True, max_length=1000)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(pk=1), name='bank_settings_singleton')]

    def clean(self):
        if self.enabled and not all(v.strip() for v in (self.bank_name, self.account_name, self.account_number)):
            raise ValidationError('Para publicar, completa banco, titular y número de cuenta.')

    @property
    def ready(self):
        return self.enabled and all(v.strip() for v in (self.bank_name, self.account_name, self.account_number))
