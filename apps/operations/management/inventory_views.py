"""Flujos de inventario exclusivos de Gerencia; reutilizan el libro de movimientos."""
import secrets
import uuid
from io import BytesIO
from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods, require_GET
from apps.catalog.models import Product
from apps.catalog.management_services import save_product
from apps.inventory.models import InventoryMovement
from apps.inventory.services import _record_movement, _require_permission
from apps.sync.services import sync_atomic
from . import security
from .views import page


class InventoryProductChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} — {obj.stock_quantity} disponibles' + (f' · {obj.barcode}' if obj.barcode else '')


class MovementForm(forms.Form):
    product = InventoryProductChoice(label='1. ¿Qué producto?', queryset=Product.objects.filter(track_inventory=True, is_combo=False).order_by('name'))
    quantity = forms.IntegerField(label='2. ¿Cuántas unidades?', min_value=1, help_text='Escribe unidades individuales; por ejemplo, una caja de 24 botellas equivale a 24 unidades.')
    reason = forms.ChoiceField(label='3. ¿Por qué sale?', choices=[('', 'Selecciona un motivo'), ('Rotura', 'Rotura'), ('Vencimiento', 'Vencimiento'), ('Consumo interno', 'Consumo interno'), ('Devolución al proveedor', 'Devolución al proveedor'), ('Otro', 'Otro motivo')])
    note = forms.CharField(label='Observación', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 2}), help_text='Puedes indicar proveedor, factura o algún detalle que ayude a identificar el movimiento.')

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        if kind == 'receipt':
            del self.fields['reason']
        else:
            self.fields['note'].help_text = 'Explica lo ocurrido. Es obligatorio si eliges Otro motivo.'

    def clean(self):
        data = super().clean()
        if data.get('reason') == 'Otro' and not data.get('note'):
            self.add_error('note', 'Explica el motivo de la salida.')
        return data


@sync_atomic('local')
@transaction.atomic
def commit_movement(data, user):
    _require_permission(user, 'receive_inventory' if data['kind'] == 'receipt' else 'adjust_inventory')
    product = Product.objects.select_for_update().get(pk=data['product'])
    # The product lock serializes repeat submissions and sales affecting its balance.
    existing = InventoryMovement.objects.filter(product=product, metadata__manager_token=data['token']).first()
    if existing:
        return existing
    if product.stock_quantity != data['before']:
        raise ValidationError('La cantidad disponible cambió. Revisa el movimiento otra vez antes de confirmar.')
    delta = data['quantity'] if data['kind'] == 'receipt' else -data['quantity']
    return _record_movement(product, delta, user, data['reason'],
        InventoryMovement.MovementType.RECEIPT if delta > 0 else InventoryMovement.MovementType.ADJUSTMENT,
        metadata={'manager_token': data['token'], 'manager_kind': data['kind']})


@require_http_methods(['GET', 'POST'])
@security.required
def move(request, kind):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'inventory.receive_inventory' if kind == 'receipt' else 'inventory.adjust_inventory')
    form = MovementForm(request.POST if request.method == 'POST' and not request.POST.get('confirmation') else None, kind=kind,
        initial={'product': request.GET.get('product')})
    review = None
    error = None
    if request.method == 'POST' and request.POST.get('confirmation'):
        try:
            data = signing.loads(request.POST['confirmation'], salt='manager.inventory', max_age=600)
            if data['user'] != request.user.pk or data['kind'] != kind:
                raise signing.BadSignature()
            if request.POST.get('action') == 'edit':
                return page(request, 'inventory_move', {'form': MovementForm(kind=kind, initial=data['fields']), 'kind': kind, 'title': 'Recibir mercadería' if kind == 'receipt' else 'Registrar salida manual'}, section='inventario')
            movement = commit_movement(data, request.user)
            messages.success(request, f'{movement.product.name}: movimiento guardado. {movement.stock_before} → {movement.stock_after} unidades.')
            return redirect('management:inventory-movements')
        except (signing.BadSignature, ValidationError, Product.DoesNotExist) as exc:
            form = MovementForm(kind=kind)
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Esta confirmación venció o no es válida. Vuelve a revisar el movimiento.'
    elif request.method == 'POST' and form.is_valid():
        product = form.cleaned_data['product']
        quantity = form.cleaned_data['quantity']
        after = product.stock_quantity + (quantity if kind == 'receipt' else -quantity)
        if after < 0:
            form.add_error('quantity', f'Solo hay {product.stock_quantity} unidades disponibles.')
        else:
            data = {'user': request.user.pk, 'product': product.pk, 'before': product.stock_quantity,
                'quantity': quantity, 'kind': kind, 'token': str(uuid.uuid4()),
                'fields': {'product': product.pk, 'quantity': quantity, 'reason': form.cleaned_data.get('reason', ''), 'note': form.cleaned_data.get('note', '')},
                'reason': ' · '.join(filter(None, [form.cleaned_data.get('reason', 'Compra / recepción'), form.cleaned_data.get('note')]))}
            review = {**data, 'after': after, 'name': product.name, 'signed': signing.dumps(data, salt='manager.inventory')}
    return page(request, 'inventory_move', {'form': form, 'review': review, 'kind': kind, 'error': error,
        'title': 'Recibir mercadería' if kind == 'receipt' else 'Registrar salida manual'}, section='inventario', status=400 if error or form.errors else 200)


class BarcodeForm(forms.Form):
    mode = forms.ChoiceField(label='¿Qué quieres hacer?', choices=[('keep', 'Guardar un código existente'), ('generate', 'Generar un código interno'), ('remove', 'Dejar el producto sin código')])
    code = forms.RegexField(label='Código existente', regex=r'^[A-Za-z0-9 ._/-]+$', max_length=48, required=False,
        help_text='Escríbelo o escanéalo aquí. Conserva los ceros iniciales. Hasta 48 caracteres.')

    def clean(self):
        data = super().clean()
        if data.get('mode') == 'keep' and not data.get('code'):
            self.add_error('code', 'Escribe el código o elige Generar un código interno.')
        return data


@require_http_methods(['GET', 'POST'])
@security.required
def barcode(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'catalog.change_product')
    product = get_object_or_404(Product, pk=pk)
    form = BarcodeForm(request.POST if request.method == 'POST' else None, initial={'mode': 'keep' if product.barcode else 'generate', 'code': product.barcode})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        code = ('BP' + secrets.token_hex(6).upper()) if data['mode'] == 'generate' else data['code'] if data['mode'] == 'keep' else None
        try:
            save_product({'barcode': code}, user=request.user, pk=pk)
            messages.success(request, 'Código guardado. Ya puedes imprimir la etiqueta.' if code else 'El producto quedó sin código de barras.')
            return redirect('management:product-barcode', pk=pk)
        except (ValidationError, IntegrityError) as exc:
            form.add_error(None, ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Este código ya pertenece a otro producto.')
    return page(request, 'barcode', {'form': form, 'product': product}, section='inventario', status=400 if form.errors else 200)


@require_GET
@security.required
def label(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    product = get_object_or_404(Product, pk=pk, barcode__isnull=False)
    from reportlab.pdfgen import canvas
    from reportlab.graphics.barcode import code128
    from reportlab.lib.units import mm
    out = BytesIO()
    pdf = canvas.Canvas(out, pagesize=(100*mm, 50*mm))
    pdf.setFont('Helvetica-Bold', 11)
    pdf.drawCentredString(50*mm, 42*mm, 'BIG PARTY')
    pdf.setFont('Helvetica', 9)
    pdf.drawCentredString(50*mm, 35*mm, product.name[:45])
    code = code128.Code128(product.barcode, barHeight=17*mm, barWidth=.35*mm, humanReadable=True)
    scale = min(1, 90*mm/code.width)
    pdf.saveState(); pdf.translate((100*mm-code.width*scale)/2, 9*mm); pdf.scale(scale, 1); code.drawOn(pdf, 0, 0); pdf.restoreState()
    pdf.showPage(); pdf.save()
    response = HttpResponse(out.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="etiqueta-{product.pk}.pdf"'
    return response
