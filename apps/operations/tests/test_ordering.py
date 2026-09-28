from datetime import timedelta

from django.contrib.auth.models import Permission
from django.test import Client
from django.utils import timezone

from apps.catalog.models import Category, Product, ProductAreaPrice, ModifierGroup, ModifierOption
from apps.inventory.models import InventoryMovement
from apps.operations.models import OperationalSession
from apps.orders import services
from apps.orders.models import TableOrder, PreparationTicket, SubAccount
from apps.payments.services import pay_full_balance
from .base import OperationsTestCase


class OrderingTestCase(OperationsTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        for user in (cls.waiter, cls.second_waiter):
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label="orders", codename__in=["add_order_line", "send_order", "manage_subaccounts"]))
        cls.food_category = Category.objects.create(name="Comida", slug="comida")
        cls.food = Product.objects.create(name="Hamburguesa", slug="hamburguesa", category=cls.food_category, base_price=65, preparation_route="KITCHEN")
        cls.group = ModifierGroup.objects.create(product=cls.food, name="Preparación", is_required=True, min_selections=1)
        cls.normal = ModifierOption.objects.create(group=cls.group, name="Normal")
        cls.no_onion = ModifierOption.objects.create(group=cls.group, name="Sin cebolla")
        cls.extras = ModifierGroup.objects.create(product=cls.food, name="Extras", selection_type="MULTIPLE", max_selections=2)
        cls.cheese = ModifierOption.objects.create(group=cls.extras, name="Extra queso", price_delta=10)
        cls.bacon = ModifierOption.objects.create(group=cls.extras, name="Extra tocino", price_delta=15)

    def setUp(self):
        self.order = self.open()
        self.enter()

    def url(self, action="", order=None):
        return f"/operacion/orden/{(order or self.order).pk}/pedido/" + (f"{action}/" if action else "")

    def action(self, action, data=None, **kwargs):
        return self.client.post(self.url(action, **kwargs), data or {}, HTTP_ACCEPT="application/json")

    def state(self, **params):
        response = self.client.get(self.url(), params, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200)
        return response.json()["state"]

    def add(self, product=None, **data):
        return self.action("agregar", {"product": (product or self.product).pk, "quantity": 1, **data})

    def draft(self):
        self.assertEqual(self.add().status_code, 200)
        return self.order.lines.get()

    def split(self):
        self.order = services.change_billing_mode(self.order, "SPLIT", self.user)
        return self.order


class CatalogOrderingTests(OrderingTestCase):
    def test_real_page_and_catalog(self):
        response = self.client.get(self.url())
        self.assertContains(response, "Pedido actual")
        self.assertContains(response, self.food.name)
        self.assertEqual(len(self.state()["products"]), 2)

    def test_inactive_internal_and_inactive_category_hidden(self):
        hidden = Category.objects.create(name="Oculta", slug="oculta", is_active=False)
        for name, options in [("Inactivo", {"is_active": False}), ("Interno", {"visible_in_pos": False}), ("Oculto", {"category": hidden})]:
            Product.objects.create(name=name, slug=name.lower(), **{"category": self.category, **options})
        self.assertEqual({p["name"] for p in self.state()["products"]}, {"Cerveza", "Hamburguesa"})
        self.assertNotIn(hidden.pk, [c["id"] for c in self.state()["categories"]])

    def test_category_filter_does_not_mix_previous_category(self):
        self.assertEqual([p["name"] for p in self.state(category=self.food_category.pk)["products"]], ["Hamburguesa"])
        self.assertEqual([p["name"] for p in self.state(category=self.category.pk)["products"]], ["Cerveza"])

    def test_search_is_combined_with_category_and_case_insensitive(self):
        self.assertEqual(self.state(category=self.food_category.pk, q="CERVEZA")["products"], [])
        self.assertEqual([p["name"] for p in self.state(category=self.food_category.pk, q=" hamb ")["products"]], ["Hamburguesa"])

    def test_area_price_in_catalog(self):
        ProductAreaPrice.objects.create(product=self.product, area=self.area, price=35)
        item = next(p for p in self.state()["products"] if p["id"] == self.product.pk)
        self.assertEqual(item["price"], "Q35.00")

    def test_out_of_stock_visible_but_cannot_add(self):
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        self.assertFalse(next(p for p in self.state()["products"] if p["id"] == self.product.pk)["available"])
        self.assertEqual(self.add().status_code, 409)
        self.assertFalse(self.order.lines.exists())

    def test_untracked_product_available_without_stock(self):
        Product.objects.filter(pk=self.food.pk).update(stock_quantity=0)
        self.assertTrue(next(p for p in self.state()["products"] if p["id"] == self.food.pk)["available"])

    def test_combo_availability_uses_components(self):
        combo, energy = self.combo()
        Product.objects.filter(pk=energy.pk).update(stock_quantity=0)
        self.assertFalse(next(p for p in self.state()["products"] if p["id"] == combo.pk)["available"])
        self.assertEqual(self.add(combo).status_code, 409)

    def test_only_active_modifier_groups_and_options(self):
        self.normal.is_active = False; self.normal.save()
        self.extras.is_active = False; self.extras.save()
        groups = next(p for p in self.state()["products"] if p["id"] == self.food.pk)["groups"]
        self.assertEqual(len(groups), 1)
        self.assertEqual([o["name"] for o in groups[0]["options"]], ["Sin cebolla"])


class OrderingAccessTests(OrderingTestCase):
    def test_other_area_and_manual_url_rejected(self):
        TableOrder.objects.filter(pk=self.order.pk).update(area=self.other_area)
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.add().status_code, 409)
        self.assertFalse(self.order.lines.exists())

    def test_closed_order_rejected(self):
        TableOrder.objects.filter(pk=self.order.pk).update(status="CLOSED")
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.add().status_code, 409)

    def test_released_link_rejected(self):
        self.order.table_links.update(released_at=timezone.now())
        self.assertEqual(self.client.get(self.url()).status_code, 404)
        self.assertEqual(self.add().status_code, 409)

    def test_table_disabled_or_out_of_service_rejected(self):
        self.table.operational_status = "OUT_OF_SERVICE"; self.table.save()
        self.assertEqual(self.add().status_code, 409)

    def test_expired_session_rejected(self):
        OperationalSession.objects.update(last_activity_at=timezone.now() - timedelta(seconds=121))
        self.assertEqual(self.add().status_code, 401)

    def test_page_requires_ordering_permission(self):
        self.waiter.user_permissions.remove(*Permission.objects.filter(codename__in=["add_order_line", "send_order", "manage_subaccounts"]))
        self.assertEqual(self.client.get(self.url()).status_code, 403)
        self.assertEqual(self.add().status_code, 403)

    def test_action_permissions_are_independent(self):
        for action, permission in [("agregar", "add_order_line"), ("enviar", "send_order"), ("cuenta", "manage_subaccounts")]:
            perm = Permission.objects.get(content_type__app_label="orders", codename=permission)
            self.waiter.user_permissions.remove(perm)
            self.assertEqual(self.action(action).status_code, 403)
            self.waiter.user_permissions.add(perm)

    def test_csrf_and_post_required_for_all_actions(self):
        strict = Client(enforce_csrf_checks=True)
        strict.cookies.update(self.client.cookies)
        for action in ("agregar", "cotizar", "aumentar", "reducir", "eliminar", "nota", "cuenta", "enviar"):
            self.assertEqual(self.client.get(self.url(action)).status_code, 405)
            self.assertEqual(strict.post(self.url(action)).status_code, 403)

    def test_client_actor_and_price_are_ignored(self):
        response = self.add(price="0.01", user_id=self.user.pk, area_id=self.other_area.pk)
        self.assertEqual(response.status_code, 200)
        line = self.order.lines.get()
        self.assertEqual(line.created_by, self.waiter)
        self.assertEqual(line.unit_price, 25)

    def test_closed_day_rejects_writes(self):
        type(self.day).objects.filter(pk=self.day.pk).update(status="CLOSED", closed_at=timezone.now(), closed_by=self.user)
        self.assertEqual(self.add().status_code, 409)
        self.assertFalse(self.order.lines.exists())


class DraftInterfaceTests(OrderingTestCase):
    def test_simple_add_and_equivalent_taps_group(self):
        for _ in range(4): self.assertEqual(self.add().status_code, 200)
        self.assertEqual(self.order.lines.get().quantity, 4)
        self.assertEqual(self.state()["draft_total"], "Q100.00")

    def test_modifiers_quantity_note_and_snapshot(self):
        response = self.add(self.food, quantity=2, modifiers=[self.no_onion.pk, self.cheese.pk], notes="Bien cocida")
        self.assertEqual(response.status_code, 200)
        line = self.order.lines.get()
        self.assertEqual(line.notes, "Bien cocida")
        self.assertEqual(line.unit_price, 75)
        self.assertEqual(response.json()["state"]["draft_total"], "Q150.00")
        self.assertEqual(response.json()["state"]["drafts"][0]["modifiers"], ["Sin cebolla", "Extra queso"])

    def test_quote_matches_backend_final_price(self):
        data = {"product": self.food.pk, "quantity": 2, "modifiers": [self.normal.pk, self.cheese.pk, self.bacon.pk]}
        response = self.action("cotizar", data)
        self.assertEqual(response.json()["quote"]["total"], "Q180.00")
        self.assertFalse(self.order.lines.exists())
        self.action("agregar", data)
        self.assertEqual(self.state()["draft_total"], "Q180.00")

    def test_required_single_maximum_and_invalid_modifiers_rejected(self):
        for modifiers in ([], [self.normal.pk, self.no_onion.pk], [self.normal.pk, self.normal.pk], [999999]):
            self.assertEqual(self.add(self.food, modifiers=modifiers).status_code, 409)
        self.assertFalse(self.order.lines.exists())

    def test_multiple_minimum_and_maximum_validated(self):
        self.extras.is_required = True; self.extras.min_selections = 2; self.extras.save()
        self.assertEqual(self.add(self.food, modifiers=[self.normal.pk, self.cheese.pk]).status_code, 409)
        third = ModifierOption.objects.create(group=self.extras, name="Otro", price_delta=5)
        self.assertEqual(self.add(self.food, modifiers=[self.normal.pk, self.cheese.pk, self.bacon.pk, third.pk]).status_code, 409)
        self.assertEqual(self.add(self.food, modifiers=[self.normal.pk, self.cheese.pk, self.bacon.pk]).status_code, 200)

    def test_area_price_snapshot_survives_price_change(self):
        price = ProductAreaPrice.objects.create(product=self.product, area=self.area, price=35)
        self.add(); price.price = 40; price.save()
        self.assertEqual(self.order.lines.get().unit_price, 35)
        self.add()
        self.assertEqual(self.order.lines.count(), 2)

    def test_bad_quantities_rejected(self):
        for quantity in ("0", "-1", "1.5", "x", "10000"):
            self.assertEqual(self.add(quantity=quantity).status_code, 409)

    def test_increase_decrease_remove_use_draft_services(self):
        line = self.draft()
        self.assertEqual(self.action("aumentar", {"line": line.pk}).status_code, 200)
        line.refresh_from_db(); self.assertEqual(line.quantity, 2)
        self.action("reducir", {"line": line.pk})
        line.refresh_from_db(); self.assertEqual(line.quantity, 1)
        self.action("eliminar", {"line": line.pk})
        line.refresh_from_db(); self.assertEqual(line.status, "CANCELLED")
        self.assertEqual(self.state()["drafts"], [])
        self.assertFalse(InventoryMovement.objects.exists())

    def test_simple_product_note_edit(self):
        line = self.draft()
        self.assertEqual(self.action("nota", {"line": line.pk, "notes": "Sin hielo"}).status_code, 200)
        line.refresh_from_db(); self.assertEqual(line.notes, "Sin hielo")

    def test_sent_lines_not_visible_or_editable(self):
        line = self.draft(); services.send_order(self.order, self.user)
        self.assertEqual(self.state()["drafts"], [])
        self.assertEqual(self.state()["draft_total"], "Q0.00")
        for action in ("aumentar", "reducir", "eliminar", "nota"):
            self.assertEqual(self.action(action, {"line": line.pk, "notes": "No"}).status_code, 409)

    def test_draft_total_excludes_sent_consumption(self):
        self.add(quantity=4); services.send_order(self.order, self.user)
        self.add(quantity=2)
        self.assertEqual(self.state()["draft_total"], "Q50.00")

    def test_drafts_survive_switch_and_new_actor_continues(self):
        line = self.draft()
        self.client.post("/operacion/bloquear/")
        self.login(user=self.second_waiter, pin="4632")
        self.assertEqual(self.state()["drafts"][0]["id"], line.pk)
        self.assertEqual(self.action("enviar").status_code, 200)
        self.assertEqual(PreparationTicket.objects.get().created_by, self.second_waiter)


class SendingInterfaceTests(OrderingTestCase):
    def test_send_generates_ticket_consumes_stock_and_clears_drafts(self):
        self.add(quantity=2)
        response = self.action("enviar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["destinations"], ["Barra 1"])
        self.assertEqual(response.json()["state"]["drafts"], [])
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 98)
        self.assertEqual(PreparationTicket.objects.get().items.get().quantity, 2)

    def test_empty_send_does_not_create_ticket(self):
        self.assertEqual(self.action("enviar").status_code, 409)
        self.assertFalse(PreparationTicket.objects.exists())

    def test_stock_failure_is_atomic_preserves_drafts_and_updates_catalog(self):
        self.add(quantity=2)
        self.add(self.food, modifiers=[self.normal.pk])
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        response = self.action("enviar")
        self.assertEqual(response.status_code, 409)
        self.assertIn("No hay existencias suficientes de Cerveza", response.json()["message"])
        self.assertEqual(len(response.json()["state"]["drafts"]), 2)
        self.assertFalse(next(p for p in response.json()["state"]["products"] if p["id"] == self.product.pk)["available"])
        self.assertFalse(PreparationTicket.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_bar_labels_are_derived_from_area(self):
        for slug, name in [("discoteca", "Barra 2"), ("premium", "Barra 3")]:
            # La otra área de fixture ya usa premium; evitar colisión del identificador.
            self.other_area.slug = "otra"; self.other_area.save()
            self.area.slug = slug; self.area.save()
            self.add()
            self.assertEqual(self.action("enviar").json()["destinations"], [name])

    def test_kitchen_and_bar_destinations(self):
        self.add(); self.add(self.food, modifiers=[self.normal.pk])
        response = self.action("enviar")
        self.assertEqual(response.json()["destinations"], ["Barra 1", "Cocina"])

    def test_none_route_sends_without_a_ticket(self):
        self.product.preparation_route = "NONE"; self.product.save()
        self.add()
        response = self.action("enviar")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["destinations"], [])
        self.assertEqual(response.json()["message"], "Pedido enviado")
        self.assertFalse(PreparationTicket.objects.exists())
        self.assertEqual(self.order.lines.get().status, "SENT")

    def test_second_send_addition_does_not_reprocess_old_lines(self):
        self.add(); self.action("enviar"); self.add(quantity=2)
        response = self.action("enviar")
        self.assertIn("Adición", response.json()["message"])
        self.assertEqual(list(PreparationTicket.objects.order_by("sequence_number").values_list("ticket_type", flat=True)), ["NEW", "ADDITION"])
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 97)

    def test_combo_sends_real_component_routes(self):
        combo, energy = self.combo()
        energy.preparation_route = "KITCHEN"; energy.save()
        self.add(combo)
        self.assertEqual(self.action("enviar").json()["destinations"], ["Barra 1", "Cocina"])
        energy.refresh_from_db(); self.assertEqual(energy.stock_quantity, 26)


class SplitInterfaceTests(OrderingTestCase):
    def setUp(self):
        super().setUp(); self.split()

    def test_no_account_prevents_add_quote_and_send(self):
        self.assertEqual(self.state()["drafts"], [])
        self.assertEqual(self.add().status_code, 409)
        self.assertEqual(self.action("cotizar", {"product": self.product.pk}).status_code, 409)
        self.assertEqual(self.action("enviar").status_code, 409)
        self.assertFalse(SubAccount.objects.exists())

    def test_create_selects_new_account_without_inventing_people(self):
        response = self.action("cuenta", {"name": "Jorge"})
        self.assertEqual(response.status_code, 200)
        account = self.order.subaccounts.get()
        self.assertEqual(response.json()["state"]["selected_account"], account.pk)
        self.assertEqual(account.name, "Jorge")

    def test_distinct_drafts_and_totals_when_switching_account(self):
        jorge = services.create_subaccount(self.order, "Jorge", self.user)
        carlos = services.create_subaccount(self.order, "Carlos", self.user)
        self.add(subaccount=jorge.pk, quantity=2)
        self.add(self.food, subaccount=carlos.pk, modifiers=[self.normal.pk])
        self.assertEqual(self.state(subaccount=jorge.pk)["draft_total"], "Q50.00")
        self.assertEqual(self.state(subaccount=carlos.pk)["draft_total"], "Q65.00")
        self.assertEqual(self.state(subaccount=carlos.pk)["drafts"][0]["name"], "Hamburguesa")

    def test_send_only_selected_account_preserves_other_drafts(self):
        first = services.create_subaccount(self.order, "Jorge", self.user)
        second = services.create_subaccount(self.order, "Carlos", self.user)
        self.add(subaccount=first.pk); self.add(subaccount=second.pk, quantity=3)
        response = self.action("enviar", {"subaccount": first.pk})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.order.lines.get(subaccount=second).status, "DRAFT")
        self.assertEqual(self.order.lines.get(subaccount=first).status, "SENT")
        self.assertEqual(PreparationTicket.objects.get().items.get().quantity, 1)

    def test_cannot_edit_another_subaccount_line(self):
        first = services.create_subaccount(self.order, "Jorge", self.user)
        second = services.create_subaccount(self.order, "Carlos", self.user)
        self.add(subaccount=first.pk)
        self.assertEqual(self.action("aumentar", {"line": self.order.lines.get().pk, "subaccount": second.pk}).status_code, 409)

    def test_closed_account_differentiated_and_rejected(self):
        account = services.create_subaccount(self.order, "Cerrada", self.user)
        SubAccount.objects.filter(pk=account.pk).update(status="CLOSED")
        self.assertTrue(self.state()["accounts"][0]["closed"])
        self.assertEqual(self.add(subaccount=account.pk).status_code, 409)
        self.assertEqual(self.client.get(self.url(), {"subaccount": account.pk}, HTTP_ACCEPT="application/json").status_code, 404)

    def test_foreign_order_subaccount_rejected(self):
        other = self.open(self.destination, split=True)
        account = services.create_subaccount(other, "Otra", self.user)
        self.assertEqual(self.add(subaccount=account.pk).status_code, 409)
        self.assertFalse(self.order.lines.exists())

    def test_unassigned_legacy_drafts_not_displayed_or_sent(self):
        legacy = services.add_product_to_order(self.order, self.product, 2, self.user)
        account = services.create_subaccount(self.order, "Jorge", self.user)
        self.add(subaccount=account.pk)
        self.assertEqual(len(self.state(subaccount=account.pk)["drafts"]), 1)
        self.action("enviar", {"subaccount": account.pk})
        legacy.refresh_from_db(); self.assertEqual(legacy.status, "DRAFT")

    def test_empty_name_rejected(self):
        self.assertEqual(self.action("cuenta", {"name": "  "}).status_code, 409)
        self.assertFalse(SubAccount.objects.exists())

    def test_removing_last_draft_deselects_account_closed_by_existing_service(self):
        account = services.create_subaccount(self.order, "Jorge", self.user)
        self.add(subaccount=account.pk)
        paid_account = services.create_subaccount(self.order, "Anterior", self.user)
        services.add_product_to_order(self.order, self.product, 1, self.user, subaccount=paid_account)
        services.send_order(self.order, self.user, subaccount=paid_account)
        pay_full_balance(paid_account, "CARD", self.user, card_approved=True)
        response = self.action("eliminar", {"line": self.order.lines.get(subaccount=account).pk, "subaccount": account.pk})
        self.assertEqual(response.status_code, 200)
        current = next(item for item in response.json()["state"]["accounts"] if item["id"] == account.pk)
        self.assertTrue(current["closed"])
        self.assertIsNone(response.json()["state"]["selected_account"])
