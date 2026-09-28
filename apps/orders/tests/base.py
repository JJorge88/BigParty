from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.catalog.models import Category, Product, ComboComponent
from apps.tables.models import VenueTable
from apps.venues.models import Area
from apps.orders.services import open_table_order
from apps.cash.services import open_business_day


class OrdersTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="orders-admin", password="Test-only-981!")
        cls.other_user = get_user_model().objects.create_superuser(username="other-operator")
        cls.day = open_business_day(cls.user)
        cls.area = Area.objects.create(name="Sport Bar", slug="sport-bar")
        cls.other_area = Area.objects.create(name="Premium", slug="premium")
        cls.table = VenueTable.objects.create(area=cls.area, name="Mesa 01", capacity=4)
        cls.destination = VenueTable.objects.create(area=cls.area, name="Mesa 02", capacity=4)
        cls.category = Category.objects.create(name="Productos", slug="productos")
        cls.product = Product.objects.create(category=cls.category, name="Cerveza", slug="cerveza",
            track_inventory=True, stock_quantity=100, base_price=25, preparation_route="AREA_BAR")

    def open(self, table=None, split=False):
        return open_table_order(table or self.table, self.user, billing_mode="SPLIT" if split else "SINGLE")

    def combo(self):
        energy = Product.objects.create(category=self.category, name="Energizante", slug="energy",
            track_inventory=True, stock_quantity=30, visible_in_pos=False, preparation_route="NONE")
        combo = Product.objects.create(category=self.category, name="Combo", slug="combo", is_combo=True, base_price=100)
        ComboComponent.objects.create(combo=combo, component=self.product, quantity=1)
        ComboComponent.objects.create(combo=combo, component=energy, quantity=4)
        return combo, energy
