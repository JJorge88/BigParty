from django.views.generic import TemplateView

from apps.core.mixins import StaffDebugPermissionMixin

from .forms import AreaSelectionForm
from .models import Category
from .services import catalog_products, get_product_price, is_product_available


class CatalogDevelopmentView(StaffDebugPermissionMixin, TemplateView):
    template_name = "catalog/development.html"
    permission_required = "catalog.view_product"

    def get(self, request, *args, **kwargs):
        form = AreaSelectionForm(request.GET)
        valid = form.is_valid()
        area = form.cleaned_data.get("area") if valid else None
        categories = list(Category.objects.all())
        rows_by_category = {category.pk: [] for category in categories}
        for product in catalog_products():
            rows_by_category[product.category_id].append({
                "product": product, "price": get_product_price(product, area),
                "available": is_product_available(product),
            })
        return self.render_to_response({
            "form": form, "selected_area": area,
            "sections": [(category, rows_by_category[category.pk]) for category in categories],
        }, status=200 if valid else 400)
