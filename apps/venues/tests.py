from io import StringIO

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from apps.tables.models import VenueTable

from .models import Area, Zone


class AreaTests(TestCase):
    def test_creation_and_ordering(self):
        last = Area.objects.create(name="Premium", slug="premium", sort_order=30)
        first = Area.objects.create(name="Sport Bar", slug="sport-bar", sort_order=10)
        self.assertEqual(list(Area.objects.all()), [first, last])
        self.assertTrue(first.is_active)
        self.assertIsNotNone(first.created_at)
        self.assertEqual(str(first), "Sport Bar")

    def test_name_and_slug_are_unique_in_python_and_database(self):
        Area.objects.create(name="Premium", slug="premium")
        for name, slug in (("Premium", "otro"), ("Otra área", "premium")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Area.objects.create(name=name, slug=slug)
            with self.subTest(slug=slug), self.assertRaises(IntegrityError), transaction.atomic():
                Area.objects.bulk_create([Area(name=name, slug=slug)])

    def test_negative_sort_order_and_invalid_slug_rejected(self):
        for fields in ({"sort_order": -1}, {"slug": "no válido"}):
            with self.subTest(fields=fields), self.assertRaises(ValidationError):
                area = Area(name="Área", slug="area")
                for name, value in fields.items():
                    setattr(area, name, value)
                area.save()


class ZoneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.area = Area.objects.create(name="Discoteca", slug="discoteca")
        cls.other = Area.objects.create(name="Sport Bar", slug="sport-bar")
        cls.zone = Zone.objects.create(area=cls.area, name="VIP", slug="vip", sort_order=10)

    def test_creation_order_and_same_names_in_different_areas(self):
        another = Zone.objects.create(area=self.other, name="VIP", slug="vip")
        earlier = Zone.objects.create(area=self.area, name="Central", slug="central", sort_order=0)
        self.assertEqual(str(self.zone), "Discoteca · VIP")
        self.assertEqual(list(self.area.zones.all()), [earlier, self.zone])
        self.assertEqual(another.name, self.zone.name)

    def test_zone_name_and_slug_unique_within_area(self):
        for name, slug in (("VIP", "otra"), ("Otra zona", "vip")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Zone.objects.create(area=self.area, name=name, slug=slug)
            with self.subTest(slug=slug), self.assertRaises(IntegrityError), transaction.atomic():
                Zone.objects.bulk_create([Zone(area=self.area, name=name, slug=slug)])

    def test_area_delete_is_protected(self):
        with self.assertRaises(ProtectedError):
            self.area.delete()

    def test_zone_with_tables_cannot_move_to_another_area(self):
        VenueTable.objects.create(area=self.area, zone=self.zone, name="Mesa 01", capacity=4)
        self.zone.area = self.other
        with self.assertRaises(ValidationError) as caught:
            self.zone.save()
        self.assertIn("area", caught.exception.message_dict)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Zone.objects.filter(pk=self.zone.pk).update(area=self.other)

    def test_empty_zone_can_move(self):
        self.zone.area = self.other
        self.zone.save()
        self.zone.refresh_from_db()
        self.assertEqual(self.zone.area, self.other)


class SeedTests(TestCase):
    def seed(self):
        call_command("seed_bigparty_defaults", stdout=StringIO())

    def test_seed_creates_only_three_areas_and_is_idempotent(self):
        self.seed()
        original = list(Area.objects.values_list("pk", "name", "slug"))
        self.seed()
        self.assertEqual(list(Area.objects.values_list("pk", "name", "slug")), original)
        self.assertEqual(list(Area.objects.values_list("name", flat=True)), ["Sport Bar", "Discoteca", "Premium"])
        self.assertEqual(Zone.objects.count(), 0)
        self.assertEqual(VenueTable.objects.count(), 0)

    def test_seed_preserves_customized_existing_records(self):
        area = Area.objects.create(
            name="Nombre configurado", slug="sport-bar", is_active=False,
            description="Descripción propia", sort_order=99,
        )
        self.seed()
        area.refresh_from_db()
        self.assertEqual(area.name, "Nombre configurado")
        self.assertFalse(area.is_active)
        self.assertEqual(area.sort_order, 99)
        self.assertEqual(area.description, "Descripción propia")

    def test_seed_name_conflict_rolls_back_all_creations(self):
        Area.objects.create(name="Discoteca", slug="identificador-personalizado")
        with self.assertRaises(CommandError):
            self.seed()
        self.assertEqual(Area.objects.count(), 1)
        self.assertFalse(Area.objects.filter(slug="sport-bar").exists())


class VenueAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_superuser(username="admin-venues", password="Only-test-71!")
        cls.area = Area.objects.create(name="Área", slug="area")
        cls.zone = Zone.objects.create(area=cls.area, name="Zona", slug="zona")

    def setUp(self):
        self.client.force_login(self.user)

    def test_models_registered_and_admin_pages_work(self):
        for model, obj in ((Area, self.area), (Zone, self.zone)):
            self.assertIn(model, admin.site._registry)
            for page, args in (("changelist", []), ("add", []), ("change", [obj.pk])):
                with self.subTest(model=model, page=page):
                    self.assertEqual(self.client.get(reverse(f"admin:venues_{model._meta.model_name}_{page}", args=args)).status_code, 200)

    def test_admin_cannot_delete_even_unreferenced_records(self):
        for model, obj in ((Area, self.area), (Zone, self.zone)):
            with self.subTest(model=model):
                url = reverse(f"admin:venues_{model._meta.model_name}_delete", args=[obj.pk])
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url, {"post": "yes"}).status_code, 403)
                self.assertTrue(model.objects.filter(pk=obj.pk).exists())
