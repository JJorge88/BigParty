from apps.sync.services import sync_atomic, track
from apps.sync.admin import SyncAdminMixin
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import transaction

from .models import Category, ComboComponent, ModifierGroup, ModifierOption, Product, ProductAreaPrice, ProductPriceHistory
from .services import update_area_price, update_base_price


class NoDeleteAdmin(SyncAdminMixin, admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Category)
class CategoryAdmin(NoDeleteAdmin):
    list_display = ("name", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")


class SyncInline(admin.TabularInline):
    def has_delete_permission(self, request, obj=None):
        from apps.sync.services import enabled
        return not enabled() and super().has_delete_permission(request, obj)


class ComboComponentInline(SyncInline):
    model = ComboComponent
    fk_name = "combo"
    extra = 0


@admin.register(Product)
class ProductAdmin(NoDeleteAdmin):
    list_display = ("name", "category", "base_price", "stock_quantity", "minimum_stock",
                    "track_inventory", "visible_in_pos", "preparation_route", "is_active")
    list_filter = ("category", "track_inventory", "visible_in_pos", "preparation_route", "is_active", "is_combo")
    search_fields = ("name", "slug")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    readonly_fields = ("stock_quantity", "created_at", "updated_at")
    fieldsets = (
        ("Información", {"fields": ("category", "name", "slug", "is_combo")}),
        ("Precio", {"fields": ("base_price",)}),
        ("Inventario", {"fields": ("track_inventory", "stock_quantity", "minimum_stock")}),
        ("Preparación", {"fields": ("preparation_route",)}),
        ("Visual", {"fields": ("image", "visible_in_pos")}),
        ("Estado", {"fields": ("is_active", "created_at", "updated_at")}),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if not request.user.has_perm("catalog.change_product_price"):
            fields.append("base_price")
        return fields

    def get_inlines(self, request, obj=None):
        return [ComboComponentInline] if obj and obj.is_combo else []

    @transaction.atomic
    @sync_atomic('local')
    def save_model(self, request, obj, form, change):
        track(obj)
        if not change:
            initial_price = obj.base_price
            if initial_price and not request.user.has_perm("catalog.change_product_price"):
                raise PermissionDenied
            obj.stock_quantity = 0
            obj.base_price = 0
            obj.save()
            if initial_price:
                update_base_price(obj, initial_price, user=request.user)
            obj.refresh_from_db()
            return
        # No reescribir stock ni precios con una copia antigua del formulario.
        current = Product.objects.select_for_update().get(pk=obj.pk)
        changed = [field for field in form.changed_data if field not in self.readonly_fields and field != "base_price"]
        for field in changed:
            setattr(current, field, form.cleaned_data[field])
        if changed:
            current.save(update_fields=[*changed, "updated_at"])
        if "base_price" in form.changed_data:
            update_base_price(current, form.cleaned_data["base_price"], user=request.user)
        obj.refresh_from_db()


@admin.register(ProductAreaPrice)
class ProductAreaPriceAdmin(NoDeleteAdmin):
    list_display = ("product", "area", "price")
    list_filter = ("area",)
    search_fields = ("product__name", "area__name")
    list_select_related = ("product", "area")
    readonly_fields = ("created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (("product", "area") if obj else ())

    def has_add_permission(self, request):
        return super().has_add_permission(request) and request.user.has_perm("catalog.change_product_price")

    def has_change_permission(self, request, obj=None):
        return super().has_change_permission(request, obj) and request.user.has_perm("catalog.change_product_price")

    @sync_atomic('local')
    def save_model(self, request, obj, form, change):
        track(obj)
        saved = update_area_price(obj.product, obj.area, obj.price, user=request.user)
        obj.pk = saved.pk
        obj.refresh_from_db()


@admin.register(ProductPriceHistory)
class ProductPriceHistoryAdmin(NoDeleteAdmin):
    list_display = ("created_at", "product", "area", "old_price", "new_price", "changed_by")
    list_filter = ("area", "created_at")
    search_fields = ("product__name", "changed_by__username")
    list_select_related = ("product", "area", "changed_by")
    readonly_fields = ("product", "area", "old_price", "new_price", "changed_by", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class ModifierOptionInline(SyncInline):
    model = ModifierOption
    extra = 0


@admin.register(ModifierGroup)
class ModifierGroupAdmin(NoDeleteAdmin):
    list_display = ("name", "product", "selection_type", "is_required", "is_active", "sort_order")
    list_filter = ("selection_type", "is_active")
    search_fields = ("name", "product__name")
    list_select_related = ("product",)
    inlines = [ModifierOptionInline]


@admin.register(ModifierOption)
class ModifierOptionAdmin(NoDeleteAdmin):
    list_display = ("name", "group", "price_delta", "is_active", "sort_order")
    list_filter = ("is_active",)
    search_fields = ("name", "group__name", "group__product__name")
    list_select_related = ("group__product",)
