"""Flujos de inventario exclusivos de Gerencia; reutilizan el libro de movimientos."""
import secrets
import uuid
from io import BytesIO
from decimal import Decimal
from apps.sync.services import save_tracked
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
        return f'{obj.name} — {obj.stock_quantity} {obj.get_inventory_unit_display()} disponibles' + (f' · {obj.barcode}' if obj.barcode else '')


class MovementForm(forms.Form):
    barcode = forms.CharField(label='Escanear código de barras (opcional)', required=False, max_length=48, help_text='Si usas lector, escanea aquí. Si no, selecciona el producto de la lista.')
    product = InventoryProductChoice(required=False, label='1. ¿Qué producto?', queryset=Product.objects.filter(track_inventory=True, is_combo=False).order_by('name'))
    quantity = forms.IntegerField(label='2. ¿Qué cantidad?', min_value=1, help_text='Usa la unidad del producto (unidades, ml o gramos). Al recibir presentaciones, convertimos la cantidad antes de confirmar.')
    receipt_unit = forms.ChoiceField(label='¿Cómo estás contando lo recibido?', choices=[('base', 'Por unidades'), ('package', 'Por cajas, botellas o bolsas')], required=False, initial='base', widget=forms.RadioSelect)
    supplier = forms.CharField(label='Proveedor', required=False, max_length=150)
    invoice = forms.CharField(label='Factura o referencia', required=False, max_length=100)
    total_cost = forms.DecimalField(label='Costo total de esta compra (Q)', required=False, min_value=0, max_digits=12, decimal_places=2)
    reason = forms.ChoiceField(label='3. ¿Por qué sale?', choices=[('', 'Selecciona un motivo'), ('Rotura', 'Rotura'), ('Vencimiento', 'Vencimiento'), ('Consumo interno', 'Consumo interno'), ('Devolución al proveedor', 'Devolución al proveedor'), ('Otro', 'Otro motivo')])
    note = forms.CharField(label='Observación', required=False, max_length=500, widget=forms.Textarea(attrs={'rows': 2}), help_text='Puedes indicar proveedor, factura o algún detalle que ayude a identificar el movimiento.')

    def __init__(self, *args, kind, **kwargs):
        super().__init__(*args, **kwargs)
        self.kind = kind
        if kind in ('receipt', 'count'):
            del self.fields['reason']
        if kind != 'receipt':
            for key in ('receipt_unit', 'supplier', 'invoice', 'total_cost'): del self.fields[key]
        if kind == 'count':
            self.fields['quantity'].min_value = 0
            self.fields['quantity'].widget.attrs['min'] = 0
            self.fields['quantity'].validators = [v for v in self.fields['quantity'].validators if not hasattr(v, 'limit_value')]
            self.fields['quantity'].label = '2. ¿Cuántas unidades contaste en total?'
            self.fields['quantity'].help_text = 'Escribe el total físico. Calculamos la diferencia por ti.'
            self.fields['note'].required = True
            self.fields['note'].label = 'Motivo de la corrección'
        elif kind == 'exit':
            self.fields['note'].help_text = 'Explica lo ocurrido. Es obligatorio si eliges Otro motivo.'

    def clean(self):
        data = super().clean()
        code = data.get('barcode', '').strip()
        product = data.get('product')
        if code:
            match = self.fields['product'].queryset.filter(barcode=code).first()
            if not match: self.add_error('barcode', 'No encontramos un producto con ese código y control de inventario.')
            elif product and product != match: self.add_error('barcode', 'El código corresponde a otro producto. Revisa tu selección.')
            else: data['product'] = match
        elif not product: self.add_error('product', 'Selecciona un producto o escanea su código.')
        if data.get('quantity') is not None and data['quantity'] < 0: self.add_error('quantity', 'La cantidad no puede ser negativa.')
        if data.get('reason') == 'Otro' and not data.get('note'):
            self.add_error('note', 'Explica el motivo de la salida.')
        return data


def movement_form_context(form, kind):
    if kind != 'receipt':
        return {}
    return {
        'fieldsets': [('1. Producto y cantidad', [form[name] for name in ('product', 'barcode', 'quantity', 'receipt_unit')])],
        'advanced_fields': [form[name] for name in ('supplier', 'invoice', 'total_cost', 'note')],
        'advanced_label': 'Agregar proveedor, factura, costo u observación (opcional)',
    }


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
    delta = data['quantity'] - product.stock_quantity if data['kind'] == 'count' else data['quantity'] if data['kind'] == 'receipt' else -data['quantity']
    if delta == 0: raise ValidationError('El conteo coincide con las existencias. No hace falta un ajuste.')
    movement = _record_movement(product, delta, user, data['reason'],
        InventoryMovement.MovementType.RECEIPT if data['kind'] == 'receipt' else InventoryMovement.MovementType.ADJUSTMENT,
        metadata={'manager_token': data['token'], 'manager_kind': data['kind'], **data.get('purchase', {})})
    if data['kind'] == 'receipt' and data.get('purchase', {}).get('total_cost'):
        product.refresh_from_db()
        product.last_unit_cost = (Decimal(data['purchase']['total_cost']) / delta).quantize(Decimal('.000001'))
        save_tracked(product, update_fields=['last_unit_cost', 'updated_at'])
    return movement


@require_http_methods(['GET', 'POST'])
@security.required
def move(request, kind):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'inventory.receive_inventory' if kind == 'receipt' else 'inventory.adjust_inventory')
    form = MovementForm(request.POST if request.method == 'POST' and not request.POST.get('confirmation') else None, kind=kind,
        initial={'product': request.GET.get('product')})
    review = None
    error = None
    verified = None
    title = {'receipt': 'Recibir mercadería', 'exit': 'Registrar salida manual', 'count': 'Corregir conteo físico'}[kind]
    if request.method == 'POST' and request.POST.get('confirmation'):
        try:
            data = signing.loads(request.POST['confirmation'], salt='manager.inventory', max_age=600)
            if data['user'] != request.user.pk or data['kind'] != kind:
                raise signing.BadSignature()
            verified = data
            if request.POST.get('action') == 'edit':
                edit_form = MovementForm(kind=kind, initial=data['fields'])
                return page(request, 'inventory_move', {'form': edit_form, 'kind': kind, 'title': title,
                    **movement_form_context(edit_form, kind)}, section='inventario')
            movement = commit_movement(data, request.user)
            messages.success(request, f'{movement.product.name}: movimiento guardado. {movement.stock_before} → {movement.stock_after} unidades.')
            return redirect('management:inventory-movements')
        except (signing.BadSignature, ValidationError, Product.DoesNotExist) as exc:
            form = MovementForm(kind=kind, initial=verified['fields'] if verified else None)
            error = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'Esta confirmación venció o no es válida. Vuelve a revisar el movimiento.'
    elif request.method == 'POST' and form.is_valid():
        product = form.cleaned_data['product']
        quantity = form.cleaned_data['quantity']
        entered_quantity = quantity
        if kind == 'receipt' and form.cleaned_data.get('receipt_unit') == 'package':
            quantity *= product.purchase_size
        after = quantity if kind == 'count' else product.stock_quantity + (quantity if kind == 'receipt' else -quantity)
        if after < 0:
            form.add_error('quantity', f'Solo hay {product.stock_quantity} unidades disponibles.')
        elif kind == 'count' and after == product.stock_quantity:
            form.add_error('quantity', 'El conteo coincide. No necesitas corregir las existencias.')
        else:
            data = {'user': request.user.pk, 'product': product.pk, 'before': product.stock_quantity,
                'quantity': quantity, 'kind': kind, 'token': str(uuid.uuid4()),
                'unit': product.get_inventory_unit_display(), 'presentation': f'{entered_quantity} × {product.purchase_size} {product.get_inventory_unit_display()}' if quantity != entered_quantity else '',
                'fields': {key: str(value) if key == 'total_cost' and value is not None else value.pk if key == 'product' else value for key, value in form.cleaned_data.items()},
                'purchase': {key: str(form.cleaned_data.get(key) or '') for key in ('supplier', 'invoice', 'total_cost')} if kind == 'receipt' else {},
                'reason': ' · '.join(filter(None, [form.cleaned_data.get('reason', 'Conteo físico' if kind == 'count' else 'Compra / recepción'), form.cleaned_data.get('note')]))}
            review = {**data, 'after': after, 'name': product.name, 'signed': signing.dumps(data, salt='manager.inventory')}
    return page(request, 'inventory_move', {'form': form, 'review': review, 'kind': kind, 'error': error,
        'title': title, **movement_form_context(form, kind)}, section='inventario', status=400 if error or form.errors else 200)


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


class LabelBatchForm(forms.Form):
    products = forms.ModelMultipleChoiceField(label='Productos con código', queryset=Product.objects.exclude(barcode__isnull=True).exclude(barcode='').order_by('name'), widget=forms.CheckboxSelectMultiple)
    copies = forms.IntegerField(label='Etiquetas de cada producto', min_value=1, max_value=50, initial=1)

    def clean(self):
        data = super().clean()
        if len(data.get('products', [])) * data.get('copies', 0) > 200:
            raise forms.ValidationError('Genera hasta 200 etiquetas por archivo.')
        return data


@require_http_methods(['GET', 'POST'])
@security.required
def label_batch(request):
    security.require(request.user, 'inventory.view_inventory')
    form = LabelBatchForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        from reportlab.pdfgen import canvas
        from reportlab.graphics.barcode import code128
        from reportlab.lib.units import mm
        out = BytesIO(); pdf = canvas.Canvas(out, pagesize=(100*mm, 50*mm))
        for product in form.cleaned_data['products']:
            for _ in range(form.cleaned_data['copies']):
                pdf.setFont('Helvetica-Bold', 11); pdf.drawCentredString(50*mm, 42*mm, 'BIG PARTY')
                pdf.setFont('Helvetica', 9); pdf.drawCentredString(50*mm, 35*mm, product.name[:45])
                code = code128.Code128(product.barcode, barHeight=17*mm, barWidth=.35*mm, humanReadable=True)
                scale = min(1, 90*mm/code.width)
                pdf.saveState(); pdf.translate((100*mm-code.width*scale)/2, 9*mm); pdf.scale(scale, 1); code.drawOn(pdf, 0, 0); pdf.restoreState(); pdf.showPage()
        pdf.save()
        response = HttpResponse(out.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = 'inline; filename="etiquetas-big-party.pdf"'
        return response
    return page(request, 'label_batch', {'form': form}, section='inventario', status=400 if form.errors else 200)
