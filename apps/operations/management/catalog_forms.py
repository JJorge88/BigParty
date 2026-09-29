from django import forms
from apps.catalog.models import Category, Product, ModifierGroup, ModifierOption, ComboComponent
from apps.venues.models import Area


class ProductForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ('name', 'slug', 'category', 'base_price', 'is_active', 'visible_in_pos', 'track_inventory',
                  'minimum_stock', 'preparation_route', 'image', 'is_combo')

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        if not user.has_perm('catalog.change_product_price'):
            self.fields['base_price'].disabled = True
        self.fields['visible_in_pos'].label = 'Visible en punto de venta'
        self.fields['image'].help_text = 'JPEG, PNG o WebP. Máximo 5 MB.'

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if image and hasattr(image, 'content_type'):
            if image.size > 5 * 1024 * 1024 or getattr(image, 'image', None) is None or image.image.format not in ('JPEG', 'PNG', 'WEBP'):
                raise forms.ValidationError('Selecciona una imagen JPEG, PNG o WebP de hasta 5 MB.')
            image.name = 'producto.' + {'JPEG': 'jpg', 'PNG': 'png', 'WEBP': 'webp'}[image.image.format]
        return image


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ('name', 'slug', 'description', 'sort_order', 'is_active')
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}


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
