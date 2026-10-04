from django import forms
from django.utils.text import slugify
from apps.catalog.models import Category, Product, ModifierGroup, ModifierOption, ComboComponent
from apps.venues.models import Area


class AutomaticSlugForm(forms.ModelForm):
    def clean_slug(self):
        value = self.cleaned_data.get('slug')
        if value:
            return value
        if self.instance.pk:
            return self.instance.slug
        maximum = self._meta.model._meta.get_field('slug').max_length
        base = slugify(self.cleaned_data.get('name', ''))[:maximum - 12] or 'producto'
        value, count = base, 2
        while self._meta.model.objects.filter(slug=value).exists():
            value = f'{base}-{count}'
            count += 1
        return value


class ProductForm(AutomaticSlugForm):
    initial_stock = forms.IntegerField(label='¿Cuántas unidades tienes ahora?', min_value=0, required=False, initial=0,
        help_text='Si activaste el conteo, escribe la cantidad disponible. Si aún no tienes, deja 0.')

    class Meta:
        model = Product
        fields = ('inventory_unit', 'purchase_size', 'purchase_label', 'uses_recipe', 'name', 'slug', 'category', 'base_price', 'is_active', 'visible_in_pos', 'track_inventory',
                  'minimum_stock', 'preparation_route', 'image', 'is_combo')

    def __init__(self, *args, user, **kwargs):
        if args and args[0] is not None:
            data = args[0].copy()
            obj = kwargs.get('instance')
            for key, default in [('inventory_unit', 'unit'), ('purchase_size', 1), ('purchase_label', 'unidad')]:
                data.setdefault(key, getattr(obj, key, default))
            args = (data, *args[1:])
        super().__init__(*args, **kwargs)
        if not user.has_perm('catalog.change_product_price'):
            self.fields['base_price'].disabled = True
        self.fields['purchase_size'].help_text = 'Ejemplo: botella de 750 ml = 750; caja de 24 botellas = 24 unidades.'
        self.fields['uses_recipe'].help_text = 'Desactiva el conteo propio. Después de guardar, agrega los ingredientes y cantidades de la receta.'
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'Se genera automáticamente si lo dejas vacío.'
        self.fields['name'].label = '¿Cómo se llama?'
        self.fields['name'].widget.attrs['placeholder'] = 'Ej. Mojito clásico'
        self.fields['category'].label = '¿En qué categoría va?'
        self.fields['base_price'].label = 'Precio de venta (Q)'
        self.fields['preparation_route'].label = '¿Dónde se prepara?'
        self.fields['track_inventory'].label = 'Llevar conteo de las unidades disponibles'
        self.fields['track_inventory'].help_text = 'Descuenta unidades con las ventas. Déjalo desactivado si no llevas conteo de este producto.'
        self.fields['preparation_route'].help_text = 'Indica dónde se prepara: barra, cocina o entrega directa.'
        self.fields['minimum_stock'].label = 'Avisar cuando queden estas unidades'
        if self.instance.pk or not user.has_perm('inventory.receive_inventory'):
            del self.fields['initial_stock']
        self.fields['visible_in_pos'].label = 'Visible en punto de venta'
        self.fields['image'].help_text = 'JPEG, PNG o WebP. Máximo 5 MB.'

    def clean(self):
        data = super().clean()
        if data.get('initial_stock') and (not data.get('track_inventory') or data.get('is_combo')):
            self.add_error('initial_stock', 'Las existencias iniciales requieren control de inventario y un producto que no sea combo.')
        return data

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'content_type'):
            if image.size > 5 * 1024 * 1024 or getattr(image, 'image', None) is None or image.image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise forms.ValidationError('Selecciona una imagen JPEG, PNG o WebP de hasta 5 MB.')
            image.name = 'producto.' + {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}[image.image.format]
        return image


class CategoryForm(AutomaticSlugForm):
    class Meta:
        model = Category
        fields = ('name', 'slug', 'description', 'sort_order', 'is_active')
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['slug'].required = False
        self.fields['slug'].help_text = 'Se genera automáticamente a partir del nombre.'


class GroupForm(forms.ModelForm):
    class Meta:
        model = ModifierGroup
        fields = ('name', 'selection_type', 'min_selections', 'max_selections', 'sort_order', 'is_required', 'is_active')


class OptionForm(forms.ModelForm):
    class Meta:
        model = ModifierOption
        fields = ('name', 'price_delta', 'sort_order', 'is_active')


class ComponentForm(forms.ModelForm):
    class Meta:
        model = ComboComponent
        fields = ('component', 'quantity', 'sort_order')


class StockForm(forms.Form):
    direction = forms.ChoiceField(label='Tipo', choices=[('plus', 'Aumentar'), ('minus', 'Reducir')])
    quantity = forms.IntegerField(label='Cantidad', min_value=1)
    reason = forms.CharField(label='Motivo', widget=forms.Textarea(attrs={'rows': 3}), max_length=2000)

    def __init__(self, *args, adjustment=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not adjustment:
            del self.fields['direction']
            self.fields['reason'].required = False


class PriceForm(forms.Form):
    area = forms.ModelChoiceField(label='Área', queryset=Area.objects.all(), required=False, empty_label='Precio general')
    price = forms.DecimalField(label='Precio (Q)', min_value=0, max_digits=10, decimal_places=2, required=False)
    use_base = forms.BooleanField(label='Usar precio general (eliminar precio especial)', required=False)

    def clean(self):
        data = super().clean()
        if data.get('use_base'):
            if not data.get('area'):
                self.add_error('area', 'Selecciona el área que volverá al precio general.')
        elif data.get('price') is None:
            self.add_error('price', 'Indica el precio.')
        return data


class StockEntryForm(StockForm):
    product = forms.ModelChoiceField(label='Producto recibido', queryset=Product.objects.filter(is_active=True, track_inventory=True, is_combo=False).order_by('name'))
    field_order = ('product', 'quantity', 'reason')


class ProductQuickForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('base_price', 'image', 'is_active', 'visible_in_pos')
        labels = {'base_price': 'Precio de venta (Q)', 'image': 'Foto del producto',
                  'is_active': 'Producto activo', 'visible_in_pos': 'Mostrar en el menú de ventas'}

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if not user.has_perm('catalog.change_product_price'):
            del self.fields['base_price']
        self.fields['is_active'].help_text = 'Desactívalo para dejar de venderlo. Su historial se conserva.'
        self.fields['visible_in_pos'].help_text = 'Si lo ocultas, el personal no lo verá en el menú de ventas.'
        self.fields['image'].help_text = 'JPEG, PNG o WebP, hasta 5 MB.'

    clean_image = ProductForm.clean_image
