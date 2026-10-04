from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction


class ValidatedModel(models.Model):
    """Validación de las escrituras individuales de este dominio."""

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class Category(ValidatedModel):
    name = models.CharField("nombre", max_length=100, unique=True)
    slug = models.SlugField("identificador", max_length=100, unique=True)
    description = models.TextField("descripción", blank=True)
    sort_order = models.PositiveIntegerField("orden", default=0)
    is_active = models.BooleanField("activa", default=True)
    created_at = models.DateTimeField("creación", auto_now_add=True)
    updated_at = models.DateTimeField("actualización", auto_now=True)

    class Meta:
        verbose_name = "Categoría"
        verbose_name_plural = "Categorías"
        ordering = ("sort_order", "name", "pk")

    def __str__(self):
        return self.name


class Product(ValidatedModel):
    inventory_unit = models.CharField('Unidad de inventario', max_length=4, choices=[('unit', 'unidades'), ('ml', 'mililitros'), ('g', 'gramos')], default='unit')
    purchase_size = models.PositiveIntegerField('Unidades por presentación de compra', default=1, validators=[MinValueValidator(1)])
    purchase_label = models.CharField('Presentación de compra', max_length=60, default='unidad')
    last_unit_cost = models.DecimalField('Último costo por unidad de inventario (Q)', max_digits=18, decimal_places=6, default=0, validators=[MinValueValidator(0)])
    uses_recipe = models.BooleanField('Descontar ingredientes mediante receta', default=False)
    barcode = models.CharField("código de barras", max_length=48, unique=True, null=True, blank=True)
    class PreparationRoute(models.TextChoices):
        AREA_BAR = "AREA_BAR", "Barra del área"
        KITCHEN = "KITCHEN", "Cocina"
        NONE = "NONE", "Sin preparación"

    category = models.ForeignKey(Category, verbose_name="categoría", on_delete=models.PROTECT, related_name="products")
    name = models.CharField("nombre", max_length=150)
    slug = models.SlugField("identificador", max_length=160, unique=True)
    base_price = models.DecimalField("precio general (Q)", max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    is_active = models.BooleanField("activo", default=True)
    visible_in_pos = models.BooleanField("visible en POS", default=True)
    track_inventory = models.BooleanField("controlar inventario", default=False)
    stock_quantity = models.PositiveIntegerField("existencias globales", default=0)
    minimum_stock = models.PositiveIntegerField("stock mínimo", default=0)
    preparation_route = models.CharField("preparación", max_length=10, choices=PreparationRoute.choices, default=PreparationRoute.NONE)
    image = models.ImageField("imagen", upload_to="products/%Y/%m/", blank=True)
    is_combo = models.BooleanField("es combo", default=False)
    created_at = models.DateTimeField("creación", auto_now_add=True)
    updated_at = models.DateTimeField("actualización", auto_now=True)

    class Meta:
        verbose_name = "Producto"
        verbose_name_plural = "Productos"
        ordering = ("category__sort_order", "name", "pk")
        permissions = [("change_product_price", "Puede cambiar precios de productos")]
        constraints = [
            models.CheckConstraint(condition=models.Q(inventory_unit__in=['unit','ml','g']), name='catalog_inventory_unit_valid'),
            models.CheckConstraint(condition=models.Q(purchase_size__gte=1), name='catalog_purchase_size_positive'),
            models.CheckConstraint(condition=models.Q(last_unit_cost__gte=0), name='catalog_unit_cost_nonnegative'),
            models.CheckConstraint(condition=models.Q(uses_recipe=False) | models.Q(track_inventory=False, is_combo=False), name='catalog_recipe_no_own_stock'),
            models.CheckConstraint(condition=models.Q(base_price__gte=0), name="catalog_product_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(preparation_route__in=["AREA_BAR", "KITCHEN", "NONE"]), name="catalog_preparation_valid"),
            models.CheckConstraint(
                condition=models.Q(is_combo=False) | models.Q(track_inventory=False, stock_quantity=0, minimum_stock=0),
                name="catalog_combo_no_own_stock",
                violation_error_message="Un combo no tiene inventario ni stock mínimo propios.",
            ),
            models.CheckConstraint(
                condition=models.Q(track_inventory=True) | models.Q(stock_quantity=0),
                name="catalog_untracked_stock_zero",
                violation_error_message="Antes de quitar el control de inventario, ajusta las existencias a cero.",
            ),
        ]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        if self.pk:
            previous = Product.objects.filter(pk=self.pk).first()
            if previous and previous.inventory_unit != self.inventory_unit and (self.stock_quantity or self.inventory_movements.exists() or self.recipe_uses.exists() or self.used_in_combos.exists()):
                raise ValidationError({'inventory_unit': 'La unidad ya tiene historial o recetas. Crea un insumo separado para no reinterpretar existencias.'})
            if (not self.track_inventory or self.is_combo) and self.recipe_uses.exists():
                raise ValidationError({'track_inventory': 'Este ingrediente se utiliza en recetas y debe conservar inventario propio.'})
            if self.uses_recipe and (self.used_in_combos.filter(combo__uses_recipe=True).exists() or self.recipe_uses.exists()):
                raise ValidationError({'uses_recipe': 'Un ingrediente no puede convertirse en receta.'})
            if not self.uses_recipe and self.recipe_ingredients.exists():
                raise ValidationError({'uses_recipe': 'Retira los ingredientes antes de desactivar la receta.'})
            if self.is_combo or not self.track_inventory:
                pending_consumption = self.inventory_movements.filter(
                    movement_type__in=["SALE", "CANCELLATION_RETURN", "REFUND_RETURN"],
                ).aggregate(total=models.Sum("quantity_delta"))["total"] or 0
                if pending_consumption < 0:
                    raise ValidationError({"track_inventory":
                        "No puedes quitar el inventario propio mientras exista consumo enviado sin reintegrar."})
            if self.is_combo and self.used_in_combos.exists():
                raise ValidationError({"is_combo": "Un componente de otro combo no puede convertirse en combo."})
            if not self.is_combo and self.combo_components.exists():
                raise ValidationError({"is_combo": "Retira los componentes antes de convertirlo en producto normal."})

    @transaction.atomic
    def save(self, *args, **kwargs):
        if self.pk:
            # Coordina cambios estructurales con ComboComponent.save().
            Product.objects.select_for_update().filter(pk=self.pk).exists()
        return super().save(*args, **kwargs)

    @property
    def is_low_stock(self):
        return self.track_inventory and self.stock_quantity <= self.minimum_stock

    @property
    def is_out_of_stock(self):
        return self.track_inventory and self.stock_quantity == 0

    @property
    def is_available_for_sale(self):
        from .services import is_product_available
        return is_product_available(self)


class ProductAreaPrice(ValidatedModel):
    product = models.ForeignKey(Product, verbose_name="producto", on_delete=models.PROTECT, related_name="area_prices")
    area = models.ForeignKey("venues.Area", verbose_name="área", on_delete=models.PROTECT)
    price = models.DecimalField("precio (Q)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField("creación", auto_now_add=True)
    updated_at = models.DateTimeField("actualización", auto_now=True)

    class Meta:
        verbose_name = "Precio por área"
        verbose_name_plural = "Precios por área"
        constraints = [
            models.UniqueConstraint(fields=("product", "area"), name="catalog_product_area_unique"),
            models.CheckConstraint(condition=models.Q(price__gte=0), name="catalog_area_price_nonnegative"),
        ]

    def __str__(self):
        return f"{self.product} · {self.area}"


class ProductPriceHistory(ValidatedModel):
    product = models.ForeignKey(Product, verbose_name="producto", on_delete=models.PROTECT, related_name="price_history")
    area = models.ForeignKey("venues.Area", verbose_name="área", on_delete=models.PROTECT, null=True, blank=True)
    old_price = models.DecimalField("precio anterior (Q)", max_digits=10, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    new_price = models.DecimalField("precio nuevo (Q)", max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="usuario", on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField("fecha", auto_now_add=True)

    class Meta:
        verbose_name = "Cambio de precio"
        verbose_name_plural = "Historial de precios"
        ordering = ("-created_at", "-pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(old_price__isnull=True) | models.Q(old_price__gte=0), name="catalog_old_price_nonnegative"),
            models.CheckConstraint(condition=models.Q(new_price__gte=0), name="catalog_new_price_nonnegative"),
        ]

    def __str__(self):
        return f"{self.product} · Q{self.new_price}"


class ModifierGroup(ValidatedModel):
    class SelectionType(models.TextChoices):
        SINGLE = "SINGLE", "Una opción"
        MULTIPLE = "MULTIPLE", "Varias opciones"

    product = models.ForeignKey(Product, verbose_name="producto", on_delete=models.PROTECT, related_name="modifier_groups")
    name = models.CharField("nombre", max_length=100)
    selection_type = models.CharField("selección", max_length=8, choices=SelectionType.choices, default=SelectionType.SINGLE)
    min_selections = models.PositiveIntegerField("mínimo de opciones", default=0)
    max_selections = models.PositiveIntegerField("máximo de opciones", default=1, validators=[MinValueValidator(1)])
    sort_order = models.PositiveIntegerField("orden", default=0)
    is_required = models.BooleanField("obligatorio", default=False)
    is_active = models.BooleanField("activo", default=True)

    class Meta:
        verbose_name = "Grupo de modificadores"
        verbose_name_plural = "Grupos de modificadores"
        ordering = ("sort_order", "name", "pk")
        constraints = [
            models.CheckConstraint(condition=models.Q(selection_type__in=["SINGLE", "MULTIPLE"]), name="catalog_selection_type_valid"),
            models.CheckConstraint(condition=models.Q(max_selections__gte=1, min_selections__lte=models.F("max_selections")), name="catalog_selection_bounds"),
            models.CheckConstraint(condition=~models.Q(selection_type="SINGLE") | models.Q(max_selections=1), name="catalog_single_max_one"),
            models.CheckConstraint(
                condition=models.Q(is_required=True, min_selections__gte=1) | models.Q(is_required=False, min_selections=0),
                name="catalog_required_min_consistent",
                violation_error_message="Un grupo obligatorio requiere mínimo 1; uno opcional requiere mínimo 0.",
            ),
        ]

    def __str__(self):
        return f"{self.product} · {self.name}"


class ModifierOption(ValidatedModel):
    group = models.ForeignKey(ModifierGroup, verbose_name="grupo", on_delete=models.PROTECT, related_name="options")
    name = models.CharField("nombre", max_length=100)
    price_delta = models.DecimalField("precio adicional (Q)", max_digits=10, decimal_places=2, default=0, validators=[MinValueValidator(0)])
    sort_order = models.PositiveIntegerField("orden", default=0)
    is_active = models.BooleanField("activa", default=True)

    class Meta:
        verbose_name = "Opción de modificador"
        verbose_name_plural = "Opciones de modificadores"
        ordering = ("sort_order", "name", "pk")
        constraints = [models.CheckConstraint(condition=models.Q(price_delta__gte=0), name="catalog_option_price_nonnegative")]

    def __str__(self):
        return self.name


class ComboComponent(ValidatedModel):
    combo = models.ForeignKey(Product, verbose_name="combo", on_delete=models.PROTECT, related_name="combo_components", limit_choices_to={"is_combo": True})
    component = models.ForeignKey(Product, verbose_name="componente", on_delete=models.PROTECT, related_name="used_in_combos", limit_choices_to={"is_combo": False})
    quantity = models.PositiveIntegerField("cantidad", validators=[MinValueValidator(1)])
    sort_order = models.PositiveIntegerField("orden", default=0)

    class Meta:
        verbose_name = "Componente de combo"
        verbose_name_plural = "Componentes de combos"
        ordering = ("sort_order", "pk")
        constraints = [
            models.UniqueConstraint(fields=("combo", "component"), name="catalog_combo_component_unique"),
            models.CheckConstraint(condition=~models.Q(combo=models.F("component")), name="catalog_combo_not_itself"),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="catalog_component_quantity_positive"),
        ]

    def clean(self):
        super().clean()
        products = dict(Product.objects.filter(pk__in=[self.combo_id, self.component_id]).values_list("pk", "is_combo"))
        errors = {}
        if self.combo_id in products and not products[self.combo_id]:
            errors["combo"] = "El producto principal debe ser un combo."
        if self.component_id in products and products[self.component_id]:
            errors["component"] = "No se permiten combos anidados."
        if self.combo_id and self.combo_id == self.component_id:
            errors["component"] = "Un combo no puede contenerse a sí mismo."
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def save(self, *args, **kwargs):
        list(Product.objects.filter(pk__in=[self.combo_id, self.component_id]).order_by("pk").select_for_update())
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.combo} · {self.quantity} × {self.component}"


class RecipeIngredient(ValidatedModel):
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='recipe_ingredients')
    ingredient = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='recipe_uses', verbose_name='Ingrediente')
    quantity = models.PositiveIntegerField('Cantidad por bebida o plato', validators=[MinValueValidator(1)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=['product', 'ingredient'], name='catalog_recipe_ingredient_unique'),
                       models.CheckConstraint(condition=~models.Q(product=models.F('ingredient')), name='catalog_recipe_not_self'),
                       models.CheckConstraint(condition=models.Q(quantity__gt=0), name='catalog_recipe_quantity_positive')]

    def clean(self):
        super().clean()
        if self.product_id and not self.product.uses_recipe:
            raise ValidationError('Activa el uso de receta en el producto antes de agregar ingredientes.')
        if self.ingredient_id and (self.ingredient.is_combo or self.ingredient.uses_recipe or not self.ingredient.track_inventory):
            raise ValidationError('El ingrediente debe tener inventario propio y no puede ser una receta ni combo.')

    @transaction.atomic
    def save(self, *args, **kwargs):
        list(Product.objects.select_for_update().filter(pk__in=[self.product_id, self.ingredient_id]).order_by('pk'))
        return super().save(*args, **kwargs)
