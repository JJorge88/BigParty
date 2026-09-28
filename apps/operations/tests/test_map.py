from datetime import timedelta
from django.contrib.auth.models import Permission
from django.utils import timezone

from apps.cash.models import BusinessDay
from apps.orders.models import TableOrder, SubAccount
from apps.orders.services import add_product_to_order, remove_draft_line, join_table_to_order
from apps.tables.models import VenueTable
from apps.venues.models import Zone
from .base import OperationsTestCase


class MapTests(OperationsTestCase):
    def data(self):
        response = self.client.get("/operacion/mesas/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()

    def tiles(self):
        return [t for g in self.data()["groups"] for t in g["tables"]]

    def test_only_active_tables_in_device_area(self):
        VenueTable.objects.create(area=self.other_area, name="Privada", capacity=2)
        VenueTable.objects.create(area=self.area, name="Inactiva", capacity=2, is_active=False)
        self.enter()
        self.assertCountEqual([t["id"] for t in self.tiles()], [self.table.pk, self.destination.pk])
        response = self.client.get("/operacion/mesas/?area=" + str(self.other_area.pk))
        self.assertNotContains(response, "Privada")
        self.assertNotContains(response, "Inactiva")

    def test_free_and_out_of_service_states(self):
        self.destination.operational_status = "OUT_OF_SERVICE"
        self.destination.save()
        self.enter()
        states = {t["id"]: t["state"] for t in self.tiles()}
        self.assertEqual(states[self.table.pk], "AVAILABLE")
        self.assertEqual(states[self.destination.pk], "OUT_OF_SERVICE")

    def test_occupied_total_time_and_responsible_come_from_order(self):
        order = self.open()
        add_product_to_order(order, self.product, 17, self.user)
        cancelled = add_product_to_order(order, self.product, 2, self.user, notes="Cancelar")
        remove_draft_line(cancelled, self.user)
        TableOrder.objects.filter(pk=order.pk).update(opened_at=timezone.now() - timedelta(minutes=78))
        self.enter()
        tile = next(t for t in self.tiles() if t["id"] == self.table.pk)
        self.assertEqual(tile["state"], "OCCUPIED")
        self.assertEqual(tile["total"], "Q425.00")
        self.assertEqual(tile["elapsed"], "01:18")
        self.assertEqual(tile["responsible"], self.user.username)

    def test_financial_states_are_derived_without_table_mutations(self):
        order = self.open()
        self.enter()
        for state in ("PAYMENT_PENDING", "PARTIALLY_PAID"):
            TableOrder.objects.filter(pk=order.pk).update(status=state)
            self.assertEqual(next(t for t in self.tiles() if t["id"] == self.table.pk)["state"], state)
        self.table.refresh_from_db()
        self.assertEqual(self.table.operational_status, "ACTIVE")

    def test_joined_table_shows_same_order_consumption(self):
        order = self.open()
        add_product_to_order(order, self.product, 2, self.user)
        join_table_to_order(order, self.destination, self.user)
        self.enter()
        self.assertEqual({t["order_id"] for t in self.tiles()}, {order.pk})
        self.assertEqual({t["total"] for t in self.tiles()}, {"Q50.00"})

    def test_zones_and_grid_fallback_sorted_by_visual_order(self):
        zone = Zone.objects.create(area=self.area, name="Pista", slug="pista")
        self.table.zone = zone; self.table.save()
        self.destination.zone = zone; self.destination.sort_order = 0; self.destination.save()
        self.table.sort_order = 10; self.table.save()
        VenueTable.objects.create(area=self.area, name="General", capacity=4)
        self.enter()
        groups = self.data()["groups"]
        self.assertEqual({g["name"] for g in groups}, {"Pista", "Área general"})
        zone_data = next(g for g in groups if g["id"] == zone.pk)
        self.assertEqual([t["id"] for t in zone_data["tables"]], [self.destination.pk, self.table.pk])
        self.assertFalse(zone_data["has_layout"])

    def test_non_overlapping_positions_enable_layout_and_overlap_falls_back(self):
        self.table.layout_x = 5; self.table.layout_y = 5; self.table.save()
        self.destination.layout_x = 40; self.destination.layout_y = 5; self.destination.save()
        self.enter()
        self.assertTrue(self.data()["groups"][0]["has_layout"])
        self.destination.layout_x = 5; self.destination.save()
        self.assertFalse(self.data()["groups"][0]["has_layout"])

    def test_no_business_day_blocks_map_and_opening(self):
        BusinessDay.objects.filter(pk=self.day.pk).update(status="CLOSED", closed_at=timezone.now(), closed_by=self.user)
        self.enter()
        response = self.client.get("/operacion/mesas/")
        self.assertContains(response, "No hay una jornada abierta.")
        self.assertFalse(self.data()["has_open_day"])
        self.assertEqual(self.open_table().status_code, 409)
        self.assertFalse(TableOrder.objects.exists())

    def test_open_day_displays_real_map(self):
        self.enter()
        self.assertTrue(self.data()["has_open_day"])
        self.assertContains(self.client.get("/operacion/mesas/"), self.table.name)


class OpenTableTests(OperationsTestCase):
    def test_single_uses_operational_identity_and_business_day(self):
        self.enter()
        response = self.open_table(user_id=self.user.pk, opened_by=self.user.pk, responsible_waiter=self.user.pk, area=self.other_area.pk)
        self.assertEqual(response.status_code, 201)
        order = TableOrder.objects.get()
        self.assertEqual(order.opened_by, self.waiter)
        self.assertEqual(order.responsible_waiter, self.waiter)
        self.assertEqual(order.area, self.area)
        self.assertEqual(order.business_day, self.day)
        self.assertEqual(order.billing_mode, "SINGLE")
        self.assertEqual(list(order.tables.all()), [self.table])
        self.assertEqual(response.json()["message"], "Mesa 01 abierta")
        self.assertEqual(response.json()["map"]["occupied_count"], 1)

    def test_split_does_not_automatically_create_people(self):
        self.enter()
        self.assertEqual(self.open_table(mode="SPLIT").status_code, 201)
        self.assertEqual(TableOrder.objects.get().billing_mode, "SPLIT")
        self.assertFalse(SubAccount.objects.exists())

    def test_out_of_service_cannot_open(self):
        self.table.operational_status = "OUT_OF_SERVICE"; self.table.save()
        self.enter()
        self.assertEqual(self.open_table().status_code, 409)
        self.assertFalse(TableOrder.objects.exists())

    def test_foreign_area_and_inactive_tables_cannot_open(self):
        foreign = VenueTable.objects.create(area=self.other_area, name="Otra", capacity=4)
        self.table.is_active = False; self.table.save()
        self.enter()
        self.assertEqual(self.open_table(table=foreign).status_code, 404)
        self.assertEqual(self.open_table().status_code, 404)
        self.assertFalse(TableOrder.objects.exists())

    def test_double_open_is_friendly_and_refreshes_map(self):
        self.enter()
        self.open_table()
        response = self.open_table()
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["message"], "La mesa acaba de ser ocupada por otro usuario.")
        self.assertEqual(response.json()["map"]["occupied_count"], 1)
        self.assertEqual(TableOrder.objects.count(), 1)

    def test_view_permission_does_not_grant_open_permission(self):
        self.waiter.user_permissions.remove(Permission.objects.get(codename="open_table_order", content_type__app_label="orders"))
        self.enter()
        self.assertEqual(self.client.get("/operacion/mesas/").status_code, 200)
        self.assertEqual(self.open_table().status_code, 403)
        self.assertFalse(TableOrder.objects.exists())

    def test_invalid_mode_cannot_create_order(self):
        self.enter()
        self.assertEqual(self.open_table(mode="INVALID").status_code, 409)
        self.assertFalse(TableOrder.objects.exists())

    def test_switching_waiter_preserves_open_order(self):
        self.enter()
        self.open_table()
        self.client.post("/operacion/bloquear/")
        self.login(user=self.second_waiter, pin="4632")
        order = TableOrder.objects.get()
        self.assertEqual(order.responsible_waiter, self.waiter)
        self.assertEqual(order.status, "OPEN")
