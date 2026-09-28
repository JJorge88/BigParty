from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, Product
from apps.venues.models import Area


class CatalogTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(name="Pruebas", slug="pruebas")
        cls.user = get_user_model().objects.create_superuser(username="catalog-admin", password="Test-only-93!")
        cls.area = Area.objects.create(name="Área de prueba", slug="area-prueba")

    def product(self, **fields):
        defaults = {"category": self.category, "name": "Producto", "slug": "producto", "base_price": "25.00"}
        return Product.objects.create(**{**defaults, **fields})
