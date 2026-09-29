import ipaddress
import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


def validate_host(value):
    if not value:
        return
    try:
        ipaddress.ip_address(value)
    except ValueError:
        if len(value) > 253 or not all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', part) for part in value.rstrip('.').split('.')):
            raise ValidationError('Usa una IP o nombre de host, sin URL ni puerto.')


class Printer(models.Model):
    class Type(models.TextChoices):
        BAR = 'BAR', 'Barra'
        KITCHEN = 'KITCHEN', 'Cocina'

    class PaperWidth(models.TextChoices):
        MM58 = '58', '58 mm'
        MM80 = '80', '80 mm'

    class Encoding(models.TextChoices):
        ASCII = 'ascii', 'ASCII compatible'
        CP850 = 'cp850', 'CP850'
        CP858 = 'cp858', 'CP858'
        UTF8 = 'utf-8', 'UTF-8 (requiere soporte físico)'

    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=40, unique=True)
    printer_type = models.CharField(max_length=7, choices=Type.choices)
    area = models.ForeignKey('venues.Area', on_delete=models.PROTECT, null=True, blank=True)
    host = models.CharField(max_length=253, blank=True, validators=[validate_host])
    port = models.PositiveIntegerField(default=9100, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    paper_width = models.CharField(max_length=2, choices=PaperWidth.choices, default=PaperWidth.MM80)
    encoding = models.CharField(max_length=10, choices=Encoding.choices, default=Encoding.ASCII)
    codepage = models.PositiveSmallIntegerField(null=True, blank=True, validators=[MaxValueValidator(255)], help_text='Número ESC t validado para el modelo físico. Vacío: no enviar selección.')
    transliterate = models.BooleanField(default=True)
    supports_cut = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('code',)
        permissions = [('manage_printers', 'Puede configurar impresoras y operar todas las áreas'), ('test_printer', 'Puede imprimir página de prueba')]
        constraints = [
            models.CheckConstraint(condition=models.Q(printer_type='BAR', area__isnull=False) | models.Q(printer_type='KITCHEN', area__isnull=True), name='printing_printer_area_type'),
            models.UniqueConstraint(fields=['area'], condition=models.Q(is_active=True, printer_type='BAR'), name='printing_active_bar_area'),
            models.UniqueConstraint(fields=['printer_type'], condition=models.Q(is_active=True, printer_type='KITCHEN'), name='printing_active_kitchen'),
            models.CheckConstraint(condition=models.Q(port__gte=1, port__lte=65535), name='printing_port_range'),
            models.CheckConstraint(condition=models.Q(paper_width__in=['58', '80']), name='printing_paper_width'),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PrintJob(models.Model):
    class Type(models.TextChoices):
        PREPARATION = 'PREPARATION', 'Comanda'
        CANCELLATION = 'CANCELLATION', 'Cancelación'
        UPDATE = 'UPDATE', 'Actualización'
        RECEIPT = 'RECEIPT', 'Recibo'
        TEST = 'TEST', 'Prueba'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pendiente'
        PRINTING = 'PRINTING', 'Imprimiendo'
        PRINTED = 'PRINTED', 'Impreso'
        FAILED = 'FAILED', 'Fallido'

    # Nullable para conservar el trabajo fallido incluso si no existe configuración de ruta.
    printer = models.ForeignKey(Printer, on_delete=models.PROTECT, null=True, blank=True, related_name='jobs')
    destination_key = models.CharField(max_length=64)
    job_type = models.CharField(max_length=12, choices=Type.choices)
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.PENDING, db_index=True)
    preparation_ticket = models.ForeignKey('orders.PreparationTicket', on_delete=models.PROTECT, null=True, blank=True, related_name='print_jobs')
    order = models.ForeignKey('orders.TableOrder', on_delete=models.PROTECT, null=True, blank=True, related_name='print_jobs')
    payment = models.ForeignKey('payments.Payment', on_delete=models.PROTECT, null=True, blank=True)
    payload_snapshot = models.JSONField(default=dict)
    reprint_of = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='copies')
    reason = models.TextField(blank=True)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    attempt_count = models.PositiveIntegerField(default=0)
    claim_token = models.UUIDField(null=True, editable=False)
    last_error = models.TextField(blank=True)
    delivery_uncertain = models.BooleanField(default=False)
    backend_used = models.CharField(max_length=20, blank=True)
    output_path = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    printing_started_at = models.DateTimeField(null=True, blank=True)
    printed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ('-created_at', '-pk')
        permissions = [('retry_print_job', 'Puede reintentar trabajos fallidos'), ('reprint_preparation_ticket', 'Puede reimprimir comandas con motivo'), ('print_customer_receipt', 'Puede imprimir recibos solicitados')]
        constraints = [
            models.UniqueConstraint(fields=['preparation_ticket', 'destination_key'], condition=models.Q(reprint_of__isnull=True, preparation_ticket__isnull=False), name='printing_ticket_destination_original'),
            models.UniqueConstraint(fields=['order'], condition=models.Q(job_type='RECEIPT', reprint_of__isnull=True), name='printing_receipt_original'),
            models.CheckConstraint(condition=models.Q(status__in=['PENDING','PRINTING','PRINTED','FAILED']), name='printing_status_valid'),
            models.CheckConstraint(condition=models.Q(job_type__in=['PREPARATION','CANCELLATION','UPDATE','RECEIPT','TEST']), name='printing_type_valid'),
            models.CheckConstraint(condition=models.Q(reprint_of__isnull=True) | ~models.Q(reason=''), name='printing_copy_reason'),
        ]

    def __str__(self):
        return f'#{self.pk} · {self.get_job_type_display()} · {self.get_status_display()}'
