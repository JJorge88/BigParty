from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from apps.tables.models import VenueTable
from apps.venues.models import Area, Zone


class TableModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area = Area.objects.create(name="Discoteca", slug="discoteca")
        cls.other = Area.objects.create(name="Sport Bar", slug="sport-bar")
        cls.zone = Zone.objects.create(area=cls.area, name="VIP", slug="vip")
        cls.other_zone = Zone.objects.create(area=cls.other, name="VIP", slug="vip")

    def create_table(self, **fields):
        return VenueTable.objects.create(**{"area": self.area, "name": "Mesa 01", "capacity": 4, **fields})

    def test_valid_table_with_optional_zone_and_default_layout(self):
        table = self.create_table()
        self.assertIsNone(table.zone)
        self.assertTrue(table.is_active)
        self.assertEqual(table.operational_status, VenueTable.OperationalStatus.ACTIVE)
        self.assertFalse(table.reservable_web)
        self.assertEqual(table.layout_width, Decimal("10.00"))
        self.assertEqual(str(table), "Discoteca · Mesa 01")
        table.zone = self.zone
        table.save()

    def test_invalid_capacity_rejected_in_python_and_database(self):
        table = self.create_table()
        for capacity in (0, -1):
            with self.subTest(capacity=capacity), self.assertRaises(ValidationError):
                self.create_table(name=f"Inválida {capacity}", capacity=capacity)
            with self.assertRaises(IntegrityError), transaction.atomic():
                VenueTable.objects.filter(pk=table.pk).update(capacity=capacity)

    def test_duplicate_name_rejected_in_same_area(self):
        self.create_table()
        with self.assertRaises(ValidationError):
            self.create_table(zone=self.zone)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VenueTable.objects.bulk_create([VenueTable(area=self.area, name="Mesa 01", capacity=4)])

    def test_same_name_allowed_in_different_area(self):
        self.create_table()
        self.create_table(area=self.other)
        self.assertEqual(VenueTable.objects.filter(name="Mesa 01").count(), 2)

    def test_zone_from_other_area_rejected_on_save(self):
        with self.assertRaises(ValidationError) as caught:
            self.create_table(zone=self.other_zone)
        self.assertIn("zone", caught.exception.message_dict)

    def test_database_enforces_zone_area_for_bulk_insert_and_update(self):
        table = self.create_table(zone=self.zone)
        for changes in ({"zone": self.other_zone}, {"area": self.other}):
            with self.subTest(changes=changes), self.assertRaises(IntegrityError), transaction.atomic():
                VenueTable.objects.filter(pk=table.pk).update(**changes)
        with self.assertRaises(IntegrityError), transaction.atomic():
            VenueTable.objects.bulk_create([
                VenueTable(area=self.area, zone=self.other_zone, name="Inválida", capacity=4),
            ])

    def test_status_web_flag_and_administrative_activation_are_independent(self):
        table = self.create_table(operational_status=VenueTable.OperationalStatus.OUT_OF_SERVICE, reservable_web=True)
        table.refresh_from_db()
        self.assertTrue(table.is_active)
        self.assertTrue(table.reservable_web)
        self.assertEqual(table.get_operational_status_display(), "Fuera de servicio")
        table.is_active = False
        table.save()
        self.assertEqual(table.operational_status, VenueTable.OperationalStatus.OUT_OF_SERVICE)

    def test_invalid_status_and_shape_rejected(self):
        table = self.create_table()
        for fields in ({"operational_status": "OCCUPIED"}, {"layout_shape": "TRIANGLE"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.create_table(name="Inválida", **fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                VenueTable.objects.filter(pk=table.pk).update(**fields)

    def test_valid_layout_including_exact_edges(self):
        table = self.create_table(
            layout_x=Decimal("90.00"), layout_y=Decimal("99.99"),
            layout_width=Decimal("10.00"), layout_height=Decimal("0.01"),
            layout_shape=VenueTable.LayoutShape.CIRCLE,
        )
        table.refresh_from_db()
        self.assertEqual(table.layout_x + table.layout_width, Decimal("100.00"))
        self.assertEqual(table.layout_y + table.layout_height, Decimal("100.00"))

    def test_invalid_layout_rejected_in_python_and_database(self):
        table = self.create_table()
        invalid = (
            {"layout_x": -1}, {"layout_x": 101}, {"layout_y": -1}, {"layout_y": 101},
            {"layout_width": 0}, {"layout_width": -1}, {"layout_width": 101},
            {"layout_height": 0}, {"layout_height": -1}, {"layout_height": 101},
            {"layout_x": 95, "layout_width": 10}, {"layout_y": 95, "layout_height": 10},
        )
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                self.create_table(name="Inválida", **fields)
            with self.assertRaises(IntegrityError), transaction.atomic():
                VenueTable.objects.filter(pk=table.pk).update(**fields)

    def test_area_and_zone_with_tables_cannot_be_deleted(self):
        self.create_table(zone=self.zone)
        with self.assertRaises(ProtectedError):
            self.zone.delete()
        with self.assertRaises(ProtectedError):
            self.area.delete()

    def test_area_with_unzoned_table_cannot_be_deleted(self):
        self.create_table()
        with self.assertRaises(ProtectedError):
            self.area.delete()

    def test_visual_order(self):
        last = self.create_table(name="A", sort_order=20)
        first = self.create_table(name="B", sort_order=10)
        self.assertEqual(list(self.area.tables.all()), [first, last])
