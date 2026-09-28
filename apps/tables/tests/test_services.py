import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.audit.models import AuditLog
from apps.tables.models import VenueTable
from apps.tables.services import get_area_table_map, update_table_configuration
from apps.venues.models import Area, Zone


class TableServiceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.actor = get_user_model().objects.create_user(username="gerente", role="GERENTE")
        cls.area = Area.objects.create(name="Discoteca", slug="discoteca")
        cls.table = VenueTable.objects.create(area=cls.area, name="Mesa 01", capacity=4)

    def test_map_structure_order_and_area_isolation(self):
        later = Zone.objects.create(area=self.area, name="Zona B", slug="b", sort_order=20)
        earlier = Zone.objects.create(area=self.area, name="Zona A", slug="a", sort_order=10, is_active=False)
        first_table = VenueTable.objects.create(
            area=self.area, zone=later, name="Primera", capacity=6, sort_order=0,
            operational_status=VenueTable.OperationalStatus.OUT_OF_SERVICE, reservable_web=True,
        )
        self.table.sort_order = 10
        self.table.is_active = False
        self.table.save()
        other = Area.objects.create(name="Otra", slug="otra")
        VenueTable.objects.create(area=other, name="Excluida", capacity=2)
        with self.assertNumQueries(2):
            result = get_area_table_map(self.area)
        self.assertEqual(set(result), {"area", "zones", "tables"})
        self.assertEqual(result["area"]["id"], self.area.pk)
        self.assertEqual([zone["id"] for zone in result["zones"]], [earlier.pk, later.pk])
        self.assertEqual([table["id"] for table in result["tables"]], [first_table.pk, self.table.pk])
        self.assertIsNone(result["tables"][1]["zone_id"])
        self.assertFalse(result["tables"][1]["is_active"])
        self.assertEqual(result["tables"][0]["capacity"], 6)
        self.assertTrue(result["tables"][0]["reservable_web"])
        self.assertEqual(result["tables"][0]["operational_status"], "OUT_OF_SERVICE")
        self.assertEqual(result["tables"][0]["layout"], {
            "x": 0.0, "y": 0.0, "width": 10.0, "height": 10.0, "shape": "RECTANGLE",
        })
        json.dumps(result)

    def test_empty_area_map(self):
        empty = Area.objects.create(name="Vacía", slug="vacia", is_active=False)
        result = get_area_table_map(empty)
        self.assertEqual(result["tables"], [])
        self.assertEqual(result["zones"], [])
        self.assertFalse(result["area"]["is_active"])

    def test_sensitive_changes_are_audited_with_actor_and_before_after(self):
        update_table_configuration(
            self.table, actor=self.actor, capacity=6, reservable_web=True,
            operational_status=VenueTable.OperationalStatus.OUT_OF_SERVICE,
        )
        self.table.refresh_from_db()
        self.assertEqual(self.table.capacity, 6)
        self.assertEqual(AuditLog.objects.count(), 3)
        log = AuditLog.objects.get(action="table.capacity_changed")
        self.assertEqual(log.data, {"field": "capacity", "before": 4, "after": 6})
        self.assertEqual(log.user, self.actor)
        self.assertEqual(log.entity, "tables.venuetable")
        self.assertEqual(log.entity_id, str(self.table.pk))
        self.assertTrue(AuditLog.objects.filter(action="table.out_of_service").exists())
        self.assertTrue(AuditLog.objects.filter(action="table.reservable_web_changed").exists())
        update_table_configuration(self.table, actor=self.actor, operational_status=VenueTable.OperationalStatus.ACTIVE)
        self.assertTrue(AuditLog.objects.filter(action="table.reactivated").exists())

    def test_no_op_does_not_log_or_update_timestamp(self):
        updated_at = self.table.updated_at
        update_table_configuration(self.table, actor=self.actor, capacity=4)
        self.table.refresh_from_db()
        self.assertEqual(self.table.updated_at, updated_at)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_layout_and_administrative_activation_do_not_generate_sensitive_events(self):
        update_table_configuration(self.table, actor=self.actor, layout_x=10, is_active=False)
        self.table.refresh_from_db()
        self.assertEqual(self.table.layout_x, 10)
        self.assertFalse(self.table.is_active)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_invalid_change_is_not_saved_or_audited(self):
        with self.assertRaises(ValidationError):
            update_table_configuration(self.table, actor=self.actor, capacity=0, reservable_web=True)
        self.table.refresh_from_db()
        self.assertEqual(self.table.capacity, 4)
        self.assertFalse(self.table.reservable_web)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_audit_failure_rolls_back_table_and_previous_events(self):
        create = AuditLog.objects.create

        def fail_second_log(**kwargs):
            if kwargs["action"] == "table.reservable_web_changed":
                raise RuntimeError("Fallo de auditoría simulado")
            return create(**kwargs)

        with patch("apps.tables.services.AuditLog.objects.create", side_effect=fail_second_log):
            with self.assertRaises(RuntimeError):
                update_table_configuration(self.table, actor=self.actor, capacity=6, reservable_web=True)
        self.table.refresh_from_db()
        self.assertEqual(self.table.capacity, 4)
        self.assertFalse(self.table.reservable_web)
        self.assertEqual(AuditLog.objects.count(), 0)

    def test_stale_instance_does_not_overwrite_unrequested_fields(self):
        update_table_configuration(self.table, actor=self.actor, capacity=6)
        update_table_configuration(self.table, actor=self.actor, reservable_web=True)
        self.table.refresh_from_db()
        self.assertEqual(self.table.capacity, 6)
        self.assertTrue(self.table.reservable_web)

    def test_unknown_fields_and_unsaved_table_rejected(self):
        with self.assertRaises(ValidationError):
            update_table_configuration(self.table, actor=self.actor, id=999)
        with self.assertRaises(ValidationError):
            update_table_configuration(VenueTable(), actor=self.actor, capacity=4)
