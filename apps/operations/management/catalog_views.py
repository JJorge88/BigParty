from datetime import date
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, F
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_GET, require_POST
from apps.catalog.models import Category, Product, ModifierGroup, ModifierOption, ComboComponent
from apps.catalog import services, management_services as writes
from apps.inventory.models import InventoryMovement
from apps.inventory.services import receive_stock, adjust_stock
from apps.venues.models import Area
from . import security, catalog_forms as forms
from .views import page


def product_cost(product):
    if product.is_combo:
        return sum((row.quantity * row.component.last_unit_cost for row in product.combo_components.all()), 0)
    if product.uses_recipe:
        return sum((row.quantity * row.ingredient.last_unit_cost for row in product.recipe_ingredients.all()), 0)
    return product.last_unit_cost


def stock_state(product):
    if product.uses_recipe:
        return ('recipe', 'Descuenta ingredientes')
    if product.is_combo:
        return ('recipe', 'Descuenta productos')
    if product.is_out_of_stock:
        return ('out', 'Agotado')
    if product.is_low_stock:
        return ('low', 'Stock bajo')
    return ('available', 'Disponible') if product.track_inventory else ('untracked', 'No necesita conteo')


def product_url(product):
    return reverse('management:product', args=[product.pk])


def error_on(form, exc):
    form.add_error(None, ' '.join(exc.messages))


def combo_selection(request, form):
    products = Product.objects.filter(is_active=True, is_combo=False).select_related('category').order_by('category__name', 'name')
    ids = request.POST.getlist('combo_component') if request.method == 'POST' else []
    quantities = request.POST.getlist('combo_quantity') if request.method == 'POST' else []
    rows = [{'product_id': ids[index] if index < len(ids) else '',
             'quantity': quantities[index] if index < len(quantities) else ''} for index in range(max(5, len(ids), len(quantities)))]
    selected = []
    if request.method == 'POST' and form.is_valid() and form.cleaned_data.get('sale_type') == 'COMBO':
        if not request.user.has_perm('catalog.add_combocomponent'):
            form.add_error(None, 'No tienes permiso para configurar productos de un combo.')
        seen = set()
        for index, row in enumerate(rows, 1):
            product_id, raw_quantity = row['product_id'].strip(), row['quantity'].strip()
            if not product_id and not raw_quantity:
                continue
            if not product_id:
                form.add_error(None, f'Elige el producto de la fila {index} del combo.')
                continue
            try:
                quantity = int(raw_quantity)
                if quantity < 1 or quantity > 999:
                    raise ValueError
            except (TypeError, ValueError):
                form.add_error(None, f'Escribe una cantidad válida en la fila {index} del combo.')
                continue
            if product_id in seen:
                form.add_error(None, 'Cada producto debe aparecer una sola vez en el combo.')
                continue
            component = products.filter(pk=product_id).first()
            if component is None:
                form.add_error(None, f'El producto de la fila {index} ya no está disponible.')
                continue
            seen.add(product_id)
            selected.append((component, quantity))
        if not selected and not form.errors:
            form.add_error(None, 'Elige al menos un producto y su cantidad para el combo.')
    return products, rows, selected


def paginate(request, rows):
    params = request.GET.copy()
    params.pop('page', None)
    return {'rows': Paginator(rows, 25).get_page(request.GET.get('page')), 'filter_query': params.urlencode()}


@require_GET
@security.required
def inventory(request):
    security.require(request.user, 'inventory.view_inventory')
    products = Product.objects.select_related('category').prefetch_related('combo_components__component', 'recipe_ingredients__ingredient')
    active = products.filter(is_active=True)
    low = Q(track_inventory=True, stock_quantity__gt=0, stock_quantity__lte=F('minimum_stock'))
    out = Q(track_inventory=True, stock_quantity=0)
    data = {'active_count': active.count(), 'low_count': active.filter(low).count(),
            'out_count': active.filter(out).count(), 'movement_count': InventoryMovement.objects.filter(created_at__date=timezone.localdate()).count(),
            'attention': list(active.filter(low | out).order_by('stock_quantity', 'name')[:10]),
            'categories': Category.objects.all()}
    state = request.GET.get('state', '')
    if state in ('low', 'out', 'untracked'):
        products = products.filter({'low': low, 'out': out, 'untracked': Q(track_inventory=False)}[state])
    query = request.GET.get('q', '').strip()[:150]
    if query:
        products = products.filter(Q(name__icontains=query) | Q(slug__icontains=query) | Q(barcode__icontains=query))
    category = request.GET.get('category', '')
    if category.isdecimal():
        products = products.filter(category_id=category)
    data.update(paginate(request, products))
    for obj in [*data['rows'], *data['attention']]:
        obj.state_code, obj.state_label = stock_state(obj)
        obj.purchase_cost_display = product_cost(obj)
    return page(request, 'inventory', data, section='inventario')


@require_GET
@security.required
def product(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    obj = get_object_or_404(services.catalog_products().prefetch_related('modifier_groups__options'), pk=pk)
    obj.state_code, obj.state_label = stock_state(obj)
    purchase_cost = product_cost(obj)
    overrides = {row.area_id: row.price for row in obj.area_prices.all()}
    maximum = services.get_combo_max_available(obj) if obj.is_combo else None
    inventory_explanation = ('Descuenta los ingredientes de su receta.' if obj.uses_recipe else
        'Descuenta los productos incluidos en el combo.' if obj.is_combo else
        'Descuenta una unidad cada vez que se vende.' if obj.track_inventory else
        'No descuenta inventario; se vende sin llevar conteo de unidades.')
    return page(request, 'product', {'product': obj, 'areas': [{'area': area, 'price': overrides.get(area.pk), 'special': area.pk in overrides} for area in Area.objects.all()],
        'history': obj.price_history.select_related('area', 'changed_by')[:15],
        'movements': obj.inventory_movements.select_related('user')[:10],
        'maximum': maximum, 'combo_available': maximum is None or maximum > 0,
        'inventory_explanation': inventory_explanation, 'purchase_cost': purchase_cost,
        'estimated_margin': obj.base_price - purchase_cost}, section='inventario')


@require_http_methods(['GET', 'POST'])
@security.required
def product_edit(request, pk=None):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'catalog.change_product' if pk else 'catalog.add_product')
    obj = get_object_or_404(Product, pk=pk) if pk else None
    form = forms.ProductForm(request.POST or None, request.FILES or None, instance=obj, user=request.user)
    combo_products, combo_rows, components = combo_selection(request, form) if not pk else (Product.objects.none(), [], [])
    if request.method == 'POST' and form.is_valid():
        try:
            obj = (writes.create_product_with_components(form.cleaned_data, components, user=request.user)
                   if not pk and form.cleaned_data.get('sale_type') == 'COMBO'
                   else writes.save_product(form.cleaned_data, user=request.user, pk=pk))
            messages.success(request, 'Producto actualizado.' if pk else ('Producto creado con sus existencias iniciales.' if form.cleaned_data.get('initial_stock') else 'Producto creado. Ya puedes revisar sus datos y registrar entradas.'))
            if not pk and form.cleaned_data.get('sale_type') == 'DRINK':
                messages.info(request, 'Ahora agrega los ingredientes y la cantidad que usa cada trago.')
                return redirect('management:product-recipe', obj.pk)
            if not pk and request.POST.get('after_save') == 'another':
                return redirect('management:product-create')
            return redirect(product_url(obj))
        except ValidationError as exc:
            error_on(form, exc)
    return page(request, 'catalog_form', {'form': form, 'title': 'Editar producto' if pk else 'Crear producto',
        'subtitle': 'Escribe el nombre, elige la categoría y coloca el precio.' if not pk else 'Actualiza sus datos. Para cambiar las existencias, registra una entrada o un ajuste.',
        'product': obj, 'back': product_url(obj) if obj else reverse('management:inventory'), 'submit': 'Guardar producto',
        'can_add_another': pk is None,
        'fieldsets': [('Datos principales', [form[key] for key in ('name', 'category', 'last_unit_cost', 'base_price', 'sale_type', 'initial_stock') if key in form.fields])],
        'advanced_fields': ([form[key] for key in ('barcode', 'image')] if not pk else [form[key] for key in (
            'preparation_route', 'track_inventory', 'is_combo', 'uses_recipe', 'minimum_stock', 'inventory_unit',
            'purchase_size', 'purchase_label', 'image', 'is_active', 'visible_in_pos', 'slug') if key in form.fields]),
        'advanced_label': 'Agregar código de barras o foto (opcional)' if not pk else 'Opciones avanzadas de producto e inventario',
        'is_product_form': True, 'combo_products': combo_products, 'combo_rows': combo_rows}, section='inventario', status=400 if form.errors else 200)


@require_http_methods(['GET', 'POST'])
@security.required
def stock(request, pk, action):
    security.require(request.user, 'inventory.view_inventory')
    from .inventory_views import move
    # Legacy URLs enter the same review flow; a POST is never written directly.
    if request.method == 'GET':
        return redirect(reverse('management:inventory-count' if action == 'adjust' else 'management:inventory-receive') + f'?product={pk}')
    data = request.POST.copy()
    data['product'] = str(pk)
    data['note'] = data.get('reason', '')
    if action == 'adjust':
        obj = get_object_or_404(Product, pk=pk)
        try: data['quantity'] = str(obj.stock_quantity + int(data.get('quantity', '')) * (-1 if data.get('direction') == 'minus' else 1))
        except ValueError: pass
    request.POST = data
    return move(request, 'count' if action == 'adjust' else 'receipt')


@require_http_methods(['GET', 'POST'])
@security.required
def price(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'catalog.change_product_price')
    obj = get_object_or_404(Product, pk=pk)
    form = forms.PriceForm(request.POST or None, initial={'price': obj.base_price})
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        try:
            if data['use_base']:
                services.remove_area_price(obj, data['area'], user=request.user)
            elif data['area']:
                services.update_area_price(obj, data['area'], data['price'], user=request.user)
            else:
                services.update_base_price(obj, data['price'], user=request.user)
            messages.success(request, 'Precio actualizado')
            return redirect(product_url(obj))
        except ValidationError as exc:
            error_on(form, exc)
    return page(request, 'catalog_form', {'form': form, 'title': 'Cambiar precio', 'subtitle': 'Precio general o especial por área. Todos los cambios conservan historial.',
        'product': obj, 'back': product_url(obj), 'submit': 'Guardar precio'}, section='inventario', status=400 if form.errors else 200)


@require_GET
@security.required
def movements(request):
    security.require(request.user, 'inventory.view_inventory')
    rows = InventoryMovement.objects.select_related('product', 'user')
    product = request.GET.get('product', '')
    if product.isdecimal():
        rows = rows.filter(product_id=product)
    kind = request.GET.get('type', '')
    if kind == 'MANUAL_EXIT':
        rows = rows.filter(metadata__manager_kind='exit')
    elif kind in InventoryMovement.MovementType.values:
        rows = rows.filter(movement_type=kind)
    try:
        selected_date = date.fromisoformat(request.GET.get('date', ''))
        rows = rows.filter(created_at__date=selected_date)
    except ValueError:
        pass
    return page(request, 'movements', {**paginate(request, rows), 'products': Product.objects.only('pk', 'name').order_by('name'),
        'types': [*InventoryMovement.MovementType.choices, ('MANUAL_EXIT', 'Salida manual')]}, section='inventario')


@require_GET
@security.required
def categories(request):
    security.require(request.user, 'inventory.view_inventory')
    return page(request, 'categories', paginate(request, Category.objects.all()), section='inventario')


@require_http_methods(['GET', 'POST'])
@security.required
def catalog_edit(request, kind, pk=None, product_id=None, group_id=None):
    security.require(request.user, 'inventory.view_inventory')
    model, form_class, label = {'category': (Category, forms.CategoryForm, 'categoría'),
        'group': (ModifierGroup, forms.GroupForm, 'grupo de modificadores'),
        'option': (ModifierOption, forms.OptionForm, 'opción'),
        'component': (ComboComponent, forms.ComponentForm, 'componente')}[kind]
    security.require(request.user, f'catalog.{"change" if pk else "add"}_{model._meta.model_name}')
    product = get_object_or_404(Product, pk=product_id) if product_id else None
    parent = get_object_or_404(ModifierGroup, pk=group_id, product=product) if kind == 'option' else product
    scope = {'product': parent} if kind == 'group' else {'group': parent} if kind == 'option' else {'combo': parent} if kind == 'component' else {}
    obj = get_object_or_404(model, pk=pk, **scope) if pk else model(**scope)
    form = form_class(request.POST or None, instance=obj)
    back = product_url(product) if product else reverse('management:categories')
    if request.method == 'POST' and form.is_valid():
        try:
            writes.save_catalog(model, form.cleaned_data, user=request.user, pk=pk, parent=parent)
            messages.success(request, 'Cambios guardados')
            if not pk and request.POST.get('after_save') == 'another':
                return redirect(request.path)
            return redirect(back)
        except ValidationError as exc:
            error_on(form, exc)
    component_title = 'Editar producto del combo' if pk else 'Agregar producto al combo'
    return page(request, 'catalog_form', {'form': form,
        'title': component_title if kind == 'component' else ('Editar ' if pk else 'Crear ') + label,
        'subtitle': f'Elige un producto ya creado y cuántos incluye {product.name}.' if kind == 'component' else 'Los cambios se aplican al catálogo operativo.',
        'product': product, 'back': back, 'submit': 'Agregar al combo' if kind == 'component' else 'Guardar cambios',
        'can_add_another': pk is None}, section='inventario', status=400 if form.errors else 200)


@require_POST
@security.required
def component_remove(request, product_id, pk):
    security.require(request.user, 'inventory.view_inventory')
    product = get_object_or_404(Product, pk=product_id, is_combo=True)
    row = get_object_or_404(ComboComponent, pk=pk, combo=product)
    writes.remove_component(row.pk, combo=product, user=request.user)
    messages.success(request, 'Componente retirado')
    return redirect(product_url(product))


@require_http_methods(['GET', 'POST'])
@security.required
def stock_create(request):
    from .inventory_views import move
    if request.method == 'GET': return redirect('management:inventory-receive')
    data = request.POST.copy(); data['note'] = data.get('reason', '')
    request.POST = data
    return move(request, 'receipt')


@require_http_methods(['GET', 'POST'])
@security.required
def product_quick_edit(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'catalog.change_product')
    obj = get_object_or_404(Product, pk=pk)
    form = forms.ProductQuickForm(request.POST if request.method == 'POST' else None,
        request.FILES or None, instance=obj, user=request.user)
    if request.method == 'POST' and form.is_valid():
        try:
            writes.save_product(form.cleaned_data, user=request.user, pk=pk)
            messages.success(request, f'Cambios guardados en {obj.name}.')
            return redirect('management:inventory')
        except ValidationError as exc:
            error_on(form, exc)
    return page(request, 'catalog_form', {'form': form, 'title': obj.name,
        'subtitle': 'Cambia el precio, la foto o si está disponible para vender.',
        'product': obj, 'quick_edit': True, 'back': reverse('management:inventory'),
        'submit': 'Guardar cambios'}, section='inventario', status=400 if form.errors else 200)
