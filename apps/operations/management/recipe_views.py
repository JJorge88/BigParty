"""Gerencia owns recipe setup; waiters retain their existing ordering screens."""
from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_http_methods
from apps.catalog.models import Product, RecipeIngredient
from apps.audit.models import AuditLog
from apps.sync.services import sync_atomic, save_tracked, delete_tracked, track
from . import security
from .views import page


class IngredientChoice(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} · {obj.get_inventory_unit_display()}'


class IngredientForm(forms.Form):
    ingredient = IngredientChoice(label='Ingrediente', queryset=Product.objects.filter(track_inventory=True, is_combo=False, uses_recipe=False).order_by('name'))
    quantity = forms.IntegerField(label='Cantidad por bebida o plato', min_value=1, help_text='En la unidad del ingrediente: por ejemplo, 45 ml de ron por mojito.')


@sync_atomic('local')
@transaction.atomic
def save_ingredient(product_id, data, *, user, remove=False):
    security.require(user, 'catalog.change_product')
    ingredient = data['ingredient']
    products = {row.pk: row for row in Product.objects.select_for_update().filter(pk__in=[product_id, ingredient.pk]).order_by('pk')}
    product = products[product_id]
    if not product.uses_recipe: raise ValidationError('Este producto ya no utiliza una receta.')
    row = RecipeIngredient.objects.filter(product=product, ingredient=ingredient).first()
    before = row.quantity if row else None
    if remove:
        if row: delete_tracked(row)
    else:
        row = row or RecipeIngredient(product=product, ingredient=products[ingredient.pk])
        row.quantity = data['quantity']; save_tracked(row)
    track(AuditLog.objects.create(user=user, action='catalog.recipe_updated', entity='catalog.product', entity_id=str(product_id), data={'ingredient': ingredient.pk, 'before': before, 'after': None if remove else data['quantity']}))


@security.required
@require_http_methods(['GET', 'POST'])
def recipe(request, pk):
    security.require(request.user, 'inventory.view_inventory')
    security.require(request.user, 'catalog.change_product')
    product = get_object_or_404(Product, pk=pk, uses_recipe=True)
    form = IngredientForm(request.POST if request.method == 'POST' else None)
    if request.method == 'POST' and form.is_valid():
        try:
            save_ingredient(pk, form.cleaned_data, user=request.user, remove=request.POST.get('action') == 'remove')
            messages.success(request, 'Receta actualizada. Las ventas ya enviadas conservan su receta original.')
            return redirect('management:product-recipe', pk=pk)
        except ValidationError as exc: form.add_error(None, ' '.join(exc.messages))
    rows = list(product.recipe_ingredients.select_related('ingredient'))
    cost = sum((row.quantity * row.ingredient.last_unit_cost for row in rows), Decimal('0'))
    return page(request, 'recipe', {'product': product, 'form': form, 'ingredients': rows, 'estimated_cost': cost,
        'missing_cost': any(not row.ingredient.last_unit_cost for row in rows)}, section='inventario', status=400 if form.errors else 200)
