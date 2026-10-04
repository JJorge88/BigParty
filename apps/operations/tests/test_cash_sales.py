from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client, TransactionTestCase, override_settings

from apps.cash import services as cash
from apps.cash.models import CashSession, CashMovement, CashHandoff
from apps.cash.tests.base import CashTestCase
from apps.catalog.models import Product, Category, ProductAreaPrice, ComboComponent, ModifierGroup, ModifierOption
from apps.inventory.models import InventoryMovement
from apps.orders import services as orders
from apps.orders.models import TableOrder, PreparationTicket, OrderLine
from apps.payments import services as payments
from apps.payments.models import Payment
from apps.operations.cash_security import REGISTER_COOKIE
from apps.tables.models import VenueTable
from .test_cash_concurrency import CashWorkstationConcurrencyTests


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CashSalesTests(CashTestCase):
    def setUp(self):
        self.cashier = get_user_model().objects.create_user(username="cashier", role="CAJERO", first_name="Carlos")
        self.cashier.set_pin("2580"); self.cashier.save()
        self.cashier.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["orders", "payments", "cash", "tables"]))
        self.station = self.register("SPORT")
        self.client.force_login(self.user)
        self.client.post("/caja/configurar/", {"register": self.station.pk})
        binding = self.client.cookies[REGISTER_COOKIE].value
        self.client.logout(); self.client.cookies[REGISTER_COOKIE] = binding
        self.client.post("/caja/acceso/", {"user_id": self.cashier.pk, "pin": "2580"})
        self.client.post("/caja/accion/abrir/", {"opening_float": "500"})
        self.cash_session = CashSession.objects.get()
        self.food = Product.objects.create(name="Hamburguesa", slug="burger", category=self.category, base_price=50,
            track_inventory=True, stock_quantity=20, preparation_route="KITCHEN")

    def create_sale(self):
        response = self.client.post("/caja/venta-rapida/nueva/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return TableOrder.objects.get(pk=int(response.json()["next"].split('/')[3]))

    def post(self, order, action, **data):
        return self.client.post(f"/caja/orden/{order.pk}/pedido/{action}/", data, HTTP_ACCEPT="application/json")

    def state(self, order):
        response = self.client.get(f"/caja/orden/{order.pk}/pedido/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["state"]

    def add(self, order, product=None, quantity=1, **extra):
        result = self.post(order, "agregar", product=(product or self.product).pk, quantity=quantity, **extra)
        self.assertEqual(result.status_code, 200, result.content)
        return result.json()["state"]

    def quote(self, order, amount=None, **extra):
        response = self.client.post(f"/caja/orden/{order.pk}/cuenta/{'mixto' if amount else 'preparar'}/", {"amount": amount or "", **extra}, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["quote"]

    def pay(self, order, method="efectivo", token=None, amount=None, **extra):
        quote = self.quote(order, amount) if token is None else {"token": token}
        return self.client.post(f"/caja/orden/{order.pk}/cuenta/{method}/", {"token": quote["token"], "received": "1000", "reference": "REV-001", **extra}, HTTP_ACCEPT="application/json")

    def send(self, order, mode="TAKE_AT_BAR", account=None, token=None):
        return self.post(order, "enviar", fulfillment_mode=mode, subaccount=account.pk if account else "", send_token=token or self.state(order)["send_token"])

    def revoke(self, codename):
        self.cashier.user_permissions.remove(Permission.objects.get(codename=codename))

    def test_creation_has_no_table_and_reuses_order_number(self):
        order = self.create_sale()
        self.assertEqual(order.order_type, "QUICK_SALE")
        self.assertIsNone(order.primary_table)
        self.assertEqual(order.cash_session, self.cash_session)
        self.assertEqual(order.area, self.area)
        self.assertEqual(order.business_day, self.day)
        self.assertEqual(order.opened_by, self.cashier)
        self.assertTrue(order.order_number.isdigit())
        self.assertFalse(order.table_links.exists())

    def test_existing_table_orders_default_table(self):
        order = self.open()
        self.assertEqual(order.order_type, "TABLE")
        self.assertEqual(order.primary_table, self.table)

    def test_database_constraint_requires_table_for_table_order(self):
        order = self.open()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableOrder.objects.filter(pk=order.pk).update(primary_table=None)

    def test_database_constraint_disallows_table_on_quick_sale(self):
        order = self.create_sale()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableOrder.objects.filter(pk=order.pk).update(primary_table=self.table)

    def test_database_constraint_requires_origin_cash_session(self):
        order = self.create_sale()
        with self.assertRaises(IntegrityError), transaction.atomic():
            TableOrder.objects.filter(pk=order.pk).update(cash_session=None)

    def test_double_create_reuses_empty_order(self):
        self.assertEqual(self.create_sale().pk, self.create_sale().pk)

    def test_get_does_not_create_orders(self):
        self.assertEqual(self.client.get("/caja/venta-rapida/").status_code, 200)
        self.assertFalse(TableOrder.objects.exists())

    def test_create_requires_permission(self):
        self.revoke("create_quick_sale")
        self.assertEqual(self.client.post("/caja/venta-rapida/nueva/", HTTP_ACCEPT="application/json").status_code, 403)

    def test_quick_sale_closed_session_rejected(self):
        cash.submit_blind_cash_count(self.cash_session, "500", self.cashier)
        self.assertEqual(self.client.post("/caja/venta-rapida/nueva/", HTTP_ACCEPT="application/json").status_code, 409)

    def test_catalog_renders_shared_components_with_cash_header(self):
        order = self.create_sale()
        response = self.client.get(f"/caja/orden/{order.pk}/pedido/")
        for text in ("Venta actual", "Alias del cliente", "Buscar producto", "Caja SPORT", "ordering.js", "Cobrar"):
            self.assertContains(response, text)
        self.assertNotContains(response, "Enviar pedido</")

    def test_catalog_uses_area_price(self):
        ProductAreaPrice.objects.create(product=self.product, area=self.area, price=30)
        order = self.create_sale()
        self.assertEqual(next(p for p in self.state(order)["products"] if p["id"] == self.product.pk)["price"], "Q30.00")
        self.add(order)
        self.assertEqual(order.lines.get().unit_price, D("30"))

    def test_draft_does_not_deduct_stock_or_emit_tickets(self):
        order = self.create_sale(); self.add(order, quantity=3)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 100)
        self.assertFalse(PreparationTicket.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_quote_is_read_only_even_for_drafts(self):
        order = self.create_sale(); self.add(order, quantity=3)
        self.assertEqual(self.quote(order)["amount"], "75.00")
        self.assertEqual(order.lines.get().status, "DRAFT")
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_drinks_cash_deducts_stock_without_bar_ticket_or_handoff(self):
        order = self.create_sale(); self.add(order, quantity=3)
        response = self.pay(order)
        self.assertEqual(response.status_code, 200, response.content)
        order.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual(order.status, "CLOSED")
        self.assertIsNotNone(order.fulfilled_at)
        self.assertEqual(self.product.stock_quantity, 97)
        self.assertFalse(order.tickets.exists())
        self.assertEqual(Payment.objects.get().cash_handoff_status, "NOT_REQUIRED")
        self.assertFalse(CashHandoff.objects.exists())
        movement = CashMovement.objects.get()
        self.assertEqual(movement.movement_type, "DIRECT_CASH_PAYMENT")
        self.assertEqual(movement.cash_session, self.cash_session)
        self.assertEqual(movement.amount, D("75"))

    def test_food_card_generates_kitchen_ticket_with_order_station_alias(self):
        order = self.create_sale(); self.add(order, self.food)
        self.assertEqual(self.post(order, "cobrar", alias="Juan camisa azul").status_code, 200)
        response = self.pay(order, "tarjeta")
        self.assertEqual(response.status_code, 200, response.content)
        ticket = order.tickets.get()
        self.assertEqual(ticket.order_number_snapshot, order.order_number)
        self.assertEqual(ticket.cash_register_snapshot, self.station.name)
        self.assertEqual(ticket.customer_alias_snapshot, "Juan camisa azul")
        self.assertEqual(ticket.table_name_snapshot, "")
        self.assertEqual(ticket.items.get().route, "KITCHEN")
        self.food.refresh_from_db(); self.assertEqual(self.food.stock_quantity, 19)
        self.assertFalse(CashMovement.objects.exists())

    def test_none_route_consumes_inventory_without_ticket(self):
        self.product.preparation_route = "NONE"; self.product.save()
        order = self.create_sale(); self.add(order); self.pay(order, "tarjeta")
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 99)
        self.assertFalse(order.tickets.exists())

    def test_combo_consumes_components_and_routes_only_food(self):
        combo = Product.objects.create(name="Combo", slug="combo", category=self.category, is_combo=True, base_price=70)
        ComboComponent.objects.create(combo=combo, component=self.product, quantity=2)
        ComboComponent.objects.create(combo=combo, component=self.food, quantity=1)
        order = self.create_sale(); self.add(order, combo, quantity=2)
        self.assertEqual(self.pay(order, "tarjeta").status_code, 200)
        self.product.refresh_from_db(); self.food.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 96)
        self.assertEqual(self.food.stock_quantity, 18)
        item = order.tickets.get().items.get()
        self.assertEqual((item.route, item.quantity), ("KITCHEN", 2))

    def test_stock_change_before_payment_rolls_back_sale(self):
        order = self.create_sale(); self.add(order, quantity=3)
        quote = self.quote(order)
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=2)
        response = self.pay(order, token=quote["token"])
        self.assertEqual(response.status_code, 409)
        self.assertIn("existencias", response.json()["message"])
        self.assertEqual(order.lines.get().status, "DRAFT")
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_failed_cash_payment_rolls_back_stock_lines_and_tickets(self):
        order = self.create_sale(); self.add(order, self.food)
        response = self.pay(order, received="1")
        self.assertEqual(response.status_code, 409)
        self.food.refresh_from_db(); self.assertEqual(self.food.stock_quantity, 20)
        self.assertEqual(order.lines.get().status, "DRAFT")
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(CashMovement.objects.exists())
        self.assertFalse(PreparationTicket.objects.exists())

    def test_verified_transfer_completes_sale_without_manager(self):
        order = self.create_sale(); self.add(order, self.food)
        response = self.pay(order, "transferencia", received_verified="yes")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("next", response.json())
        order.refresh_from_db()
        self.assertEqual(order.status, "CLOSED")
        self.assertEqual(Payment.objects.get().status, "CONFIRMED")
        self.assertTrue(order.tickets.exists())

    def test_transfer_pending_does_not_complete_or_send_kitchen(self):
        order = self.create_sale(); self.add(order, self.food)
        response = self.pay(order, "transferencia")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("next", response.json())
        self.assertIn("No entregar", response.json()["message"])
        order.refresh_from_db(); self.assertEqual(order.status, "PAYMENT_PENDING")
        self.assertFalse(order.tickets.exists())
        self.food.refresh_from_db(); self.assertEqual(self.food.stock_quantity, 19)
        self.assertEqual(Payment.objects.get().status, "PENDING")

    def test_deposit_pending_and_missing_reference_rollback(self):
        order = self.create_sale(); self.add(order)
        self.assertEqual(self.pay(order, "deposito", reference="").status_code, 409)
        self.assertEqual(order.lines.get().status, "DRAFT")
        self.assertEqual(self.pay(order, "deposito").status_code, 200)
        self.assertEqual(Payment.objects.get().status, "PENDING")

    def test_mixed_reserves_inventory_once_and_completes_only_after_last_payment(self):
        order = self.create_sale(); self.add(order, self.food, quantity=6)
        self.assertEqual(self.pay(order, amount="100").status_code, 200)
        self.assertFalse(order.tickets.exists())
        self.food.refresh_from_db(); self.assertEqual(self.food.stock_quantity, 14)
        order.refresh_from_db(); self.assertEqual(order.status, "PARTIALLY_PAID")
        self.assertEqual(self.pay(order, "tarjeta").status_code, 200)
        order.refresh_from_db(); self.assertEqual(order.status, "CLOSED")
        self.food.refresh_from_db(); self.assertEqual(self.food.stock_quantity, 14)
        self.assertEqual(order.tickets.get().items.get().quantity, 6)
        self.assertEqual(Payment.objects.count(), 2)

    def test_mixed_pending_cannot_close_until_verified(self):
        order = self.create_sale(); self.add(order, self.food, quantity=2)
        self.pay(order, amount="25"); self.pay(order, "transferencia")
        response = self.client.post(f"/caja/orden/{order.pk}/cuenta/cerrar/", HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 409)
        pending = Payment.objects.get(status="PENDING")
        payments.confirm_pending_payment(pending, self.user)
        self.assertEqual(self.client.post(f"/caja/orden/{order.pk}/cuenta/cerrar/", HTTP_ACCEPT="application/json").status_code, 200)
        self.assertEqual(order.tickets.count(), 1)

    def test_rejected_transfer_can_be_paid_again_without_double_stock(self):
        order = self.create_sale(); self.add(order)
        self.pay(order, "transferencia")
        payments.reject_pending_payment(Payment.objects.get(), self.user, "Referencia incorrecta")
        self.assertEqual(self.pay(order).status_code, 200)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 99)

    def test_payment_replay_cannot_duplicate_cash(self):
        order = self.create_sale(); self.add(order)
        token = self.quote(order)["token"]
        self.assertEqual(self.pay(order, token=token).status_code, 200)
        self.assertEqual(self.pay(order, token=token).status_code, 409)
        self.assertEqual(Payment.objects.count(), 1)

    def test_stale_quote_rejected_after_draft_quantity_change(self):
        order = self.create_sale(); self.add(order)
        token = self.quote(order)["token"]
        self.add(order)
        self.assertEqual(self.pay(order, token=token).status_code, 409)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_alias_optional_and_length_checked(self):
        order = self.create_sale(); self.add(order)
        self.assertEqual(self.post(order, "cobrar", alias="x" * 101).status_code, 409)
        self.assertEqual(self.post(order, "cobrar", alias="").status_code, 200)
        self.assertEqual(self.pay(order).status_code, 200)

    def test_no_edit_or_extra_items_after_first_payment(self):
        order = self.create_sale(); self.add(order, quantity=3); self.pay(order, amount="25")
        self.assertEqual(self.post(order, "agregar", product=self.food.pk, quantity=1).status_code, 409)
        self.assertEqual(self.post(order, "nota", line=order.lines.get().pk, notes="x").status_code, 409)

    def test_completion_screen_reports_sale_only_and_kitchen(self):
        order = self.create_sale(); self.add(order, self.food); self.pay(order, "tarjeta")
        response = self.client.get(f"/caja/orden/{order.pk}/completada/")
        self.assertContains(response, "Venta completada")
        self.assertContains(response, "Pedido enviado a Cocina")
        self.assertContains(response, "Q50.00")
        self.assertNotContains(response, "500.00")
        self.assertNotContains(response, "expected_cash")

    def test_pending_sale_not_completada(self):
        order = self.create_sale(); self.add(order); self.pay(order, "deposito")
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/completada/").status_code, 409)

    def test_quick_sale_requires_record_payment_and_close_permission(self):
        order = self.create_sale(); self.add(order)
        token = self.quote(order)["token"]
        self.revoke("close_order")
        self.assertEqual(self.pay(order, token=token).status_code, 403)
        self.assertFalse(InventoryMovement.objects.exists())
        self.revoke("record_payment")
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/cuenta/").status_code, 403)

    def test_tables_only_same_area_and_occupied_selectable(self):
        self.open()
        foreign = VenueTable.objects.create(name="Privada Premium", area=self.other_area, capacity=4)
        orders.open_table_order(foreign, self.user)
        response = self.client.get("/caja/mesas/")
        self.assertContains(response, "Mesa 01")
        self.assertContains(response, "Cargar productos")
        self.assertNotContains(response, "Premium")
        self.assertNotContains(response, "efectivo esperado")

    def test_item_permissions_apply_to_quote_and_addition(self):
        order = self.create_sale(); self.revoke("add_order_line")
        for action in ("cotizar", "agregar"):
            self.assertEqual(self.post(order, action, product=self.product.pk, quantity=1).status_code, 403)

    def test_modifiers_notes_quantity_and_snapshots(self):
        group = ModifierGroup.objects.create(product=self.food, name="Extras", min_selections=0, max_selections=1)
        option = ModifierOption.objects.create(group=group, name="Queso", price_delta=5)
        order = self.create_sale()
        self.add(order, self.food, quantity=2, modifiers=[option.pk], notes="Sin cebolla")
        line = order.lines.get()
        self.assertEqual(line.unit_price, D("55"))
        self.assertEqual(line.notes, "Sin cebolla")
        self.assertEqual(self.pay(order, "tarjeta").status_code, 200)
        self.assertEqual(order.tickets.get().items.get().notes_snapshot, "Sin cebolla")

    def test_backend_quick_cash_cannot_create_waiter_handoff(self):
        order = self.create_sale(); self.add(order, quantity=2); self.pay(order, amount="25")
        with self.assertRaises(ValidationError):
            payments.pay_full_balance(order, "CASH", self.user)
        self.assertFalse(CashHandoff.objects.exists())

    def test_counted_session_blocks_card_and_table_confirmation(self):
        sale = self.create_sale(); self.add(sale); token = self.quote(sale)["token"]
        table_order = self.open(); self.add(table_order); send_token = self.state(table_order)["send_token"]
        cash.submit_blind_cash_count(self.cash_session, "500", self.cashier)
        self.assertEqual(self.pay(sale, "tarjeta", token=token).status_code, 409)
        self.assertEqual(self.send(table_order, token=send_token).status_code, 409)
        self.assertFalse(Payment.objects.exists())
        self.assertFalse(InventoryMovement.objects.exists())

    def test_closed_session_blocks_new_sale(self):
        cash.submit_blind_cash_count(self.cash_session, "500", self.cashier)
        cash.close_cash_session(self.cash_session, self.cashier)
        self.assertEqual(self.client.post("/caja/venta-rapida/nueva/", HTTP_ACCEPT="application/json").status_code, 409)

    def test_foreign_modifier_rejected_without_creating_line(self):
        group = ModifierGroup.objects.create(product=self.food, name="Extras")
        option = ModifierOption.objects.create(group=group, name="Queso", price_delta=5)
        order = self.create_sale()
        self.assertEqual(self.post(order, "agregar", product=self.product.pk, modifiers=[option.pk], quantity=1).status_code, 409)
        self.assertFalse(order.lines.exists())

    def test_pending_food_note_does_not_emit_update_before_kitchen_dispatch(self):
        order = self.create_sale(); self.add(order, self.food); self.pay(order, "deposito")
        orders.update_sent_line_note(order.lines.get(), "Sin sal", self.user)
        self.assertFalse(order.tickets.exists())
        payments.confirm_pending_payment(order.payments.get(), self.user)
        payments.close_order(order, self.user)
        self.assertEqual(order.tickets.get().items.get().notes_snapshot, "Sin sal")

    def test_empty_table_not_opened_by_cash_flow(self):
        response = self.client.get("/caja/mesas/")
        self.assertContains(response, "No disponible para cargar")
        self.assertFalse(TableOrder.objects.exists())

    def test_table_from_other_area_blocked_in_url(self):
        from apps.tables.models import VenueTable
        table = VenueTable.objects.create(name="Privada", area=self.other_area, capacity=4)
        order = orders.open_table_order(table, self.user)
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/pedido/").status_code, 409)
        self.assertEqual(self.post(order, "agregar", product=self.product.pk).status_code, 409)

    def test_table_permission_required(self):
        order = self.open(); self.revoke("add_products_from_cash_register")
        self.assertEqual(self.client.get("/caja/mesas/").status_code, 403)
        self.assertEqual(self.post(order, "agregar", product=self.product.pk).status_code, 403)

    def test_table_take_at_bar_updates_total_stock_without_bar_ticket(self):
        order = self.open(); self.add(order, quantity=2)
        self.assertEqual(self.send(order).status_code, 200)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 98)
        self.assertEqual(orders.get_order_committed_total(order), D("50"))
        self.assertFalse(order.tickets.exists())
        self.assertFalse(Payment.objects.exists())

    def test_table_food_take_at_bar_still_goes_to_kitchen(self):
        order = self.open(); self.add(order, self.food)
        self.assertEqual(self.send(order).status_code, 200)
        self.assertEqual(order.tickets.get().items.get().route, "KITCHEN")

    def test_send_to_table_routes_bar_and_kitchen_only_new_addition(self):
        order = self.open(); self.add(order, quantity=2); self.send(order, "NORMAL_TABLE_SEND")
        self.add(order, self.food); self.add(order)
        self.assertEqual(self.send(order, "NORMAL_TABLE_SEND").status_code, 200)
        ticket = order.tickets.latest("pk")
        self.assertEqual(ticket.ticket_type, "ADDITION")
        self.assertCountEqual(list(ticket.items.values_list("route", "quantity")), [("AREA_BAR", 1), ("KITCHEN", 1)])
        self.assertEqual(order.tickets.count(), 2)

    def test_cash_drafts_do_not_merge_with_waiter_drafts(self):
        order = self.open()
        waiter_line = orders.add_product_to_order(order, self.product, 1, self.user)
        self.add(order, quantity=2)
        self.assertEqual(order.lines.count(), 2)
        self.assertEqual(len(self.state(order)["drafts"]), 1)
        self.assertEqual(self.send(order).status_code, 200)
        waiter_line.refresh_from_db(); self.assertEqual(waiter_line.status, "DRAFT")
        orders.send_order(order, self.user)
        self.assertEqual(order.tickets.get().items.get().quantity, 1)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 97)

    def test_waiter_send_does_not_send_cash_drafts(self):
        order = self.open(); self.add(order, quantity=2)
        orders.add_product_to_order(order, self.food, 1, self.user)
        orders.send_order(order, self.user)
        self.assertEqual(order.lines.get(product=self.product).status, "DRAFT")
        self.assertEqual(order.lines.get(product=self.food).status, "SENT")

    def test_cash_cannot_edit_waiter_line(self):
        order = self.open(); line = orders.add_product_to_order(order, self.product, 1, self.user)
        self.assertEqual(self.post(order, "eliminar", line=line.pk).status_code, 409)
        line.refresh_from_db(); self.assertEqual(line.status, "DRAFT")

    def test_split_requires_selected_open_subaccount(self):
        order = self.open(split=True)
        self.assertEqual(self.post(order, "agregar", product=self.product.pk).status_code, 409)
        account = orders.create_subaccount(order, "Juan", self.user)
        self.add(order, subaccount=account.pk)
        self.assertEqual(order.lines.get().subaccount, account)

    def test_closed_subaccount_rejected_new_subaccount_supported(self):
        order = self.open(split=True)
        account = orders.create_subaccount(order, "Juan", self.user)
        orders.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        orders.send_order(order, self.user, subaccount=account)
        payments.pay_full_balance(account, "CARD", self.user, card_approved=True)
        self.assertEqual(self.post(order, "agregar", product=self.product.pk, subaccount=account.pk).status_code, 409)
        response = self.post(order, "cuenta", name="Juan segunda visita")
        self.assertEqual(response.status_code, 200)
        self.add(order, subaccount=response.json()["state"]["selected_account"])
        self.assertEqual(order.subaccounts.count(), 2)

    def test_split_send_selected_account_only(self):
        order = self.open(split=True)
        a = orders.create_subaccount(order, "A", self.user); b = orders.create_subaccount(order, "B", self.user)
        self.add(order, subaccount=a.pk); state = self.add(order, self.food, subaccount=b.pk)
        self.assertEqual(self.send(order, account=b, token=state["send_token"]).status_code, 200)
        self.assertEqual(order.lines.get(subaccount=a).status, "DRAFT")
        self.assertEqual(order.lines.get(subaccount=b).status, "SENT")

    def test_table_send_revalidates_stock(self):
        order = self.open(); self.add(order, quantity=2)
        token = self.state(order)["send_token"]
        Product.objects.filter(pk=self.product.pk).update(stock_quantity=0)
        self.assertEqual(self.send(order, token=token).status_code, 409)
        self.assertEqual(order.lines.get().status, "DRAFT")

    def test_stale_send_token_rejected_and_no_previous_items_reissued(self):
        order = self.open(); self.add(order)
        token = self.state(order)["send_token"]
        self.assertEqual(self.send(order, "NORMAL_TABLE_SEND", token=token).status_code, 200)
        self.add(order)
        self.assertEqual(self.send(order, token=token).status_code, 409)
        self.assertEqual(order.tickets.count(), 1)

    def test_stale_closed_order_rejected(self):
        order = self.open()
        payments.close_order(order, self.user)
        self.assertEqual(self.post(order, "agregar", product=self.product.pk).status_code, 409)

    def test_table_payment_routes_are_not_available(self):
        order = self.open(); self.add(order)
        self.assertEqual(self.post(order, "cobrar").status_code, 409)
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/cuenta/").status_code, 409)

    def test_fulfillment_mode_invalid_rejected(self):
        order = self.open(); self.add(order)
        self.assertEqual(self.send(order, "UNKNOWN").status_code, 409)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_quick_sale_cannot_send_before_payment(self):
        order = self.create_sale(); self.add(order)
        self.assertEqual(self.send(order).status_code, 409)
        with self.assertRaises(ValidationError): orders.send_order(order, self.cashier)
        self.assertFalse(InventoryMovement.objects.exists())

    def test_other_station_cannot_read_or_pay_quick_sale(self):
        order = self.create_sale(); self.add(order)
        other = cash.open_cash_session(self.register("OTHER", self.area), self.cashier, "0", self.cashier)
        TableOrder.objects.filter(pk=order.pk).update(cash_session=other)
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/pedido/").status_code, 409)
        self.assertEqual(self.client.get(f"/caja/orden/{order.pk}/cuenta/").status_code, 409)

    def test_pin_session_change_invalidates_payment_confirmation(self):
        order = self.create_sale(); self.add(order); token = self.quote(order)["token"]
        self.client.post("/caja/bloquear/")
        self.client.post("/caja/acceso/", {"user_id": self.cashier.pk, "pin": "2580"})
        self.assertEqual(self.pay(order, token=token).status_code, 409)

    def test_post_and_csrf_required(self):
        order = self.create_sale()
        urls = ["/caja/venta-rapida/nueva/", f"/caja/orden/{order.pk}/pedido/agregar/", f"/caja/orden/{order.pk}/pedido/enviar/", f"/caja/orden/{order.pk}/cuenta/efectivo/"]
        protected = Client(enforce_csrf_checks=True); protected.cookies.update(self.client.cookies)
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 405)
            self.assertEqual(protected.post(url).status_code, 403)

    def test_cash_active_stays_private_and_links_enabled(self):
        response = self.client.get("/caja/activa/")
        self.assertContains(response, '/caja/venta-rapida/')
        self.assertContains(response, '/caja/mesas/')
        self.assertNotContains(response, 'Disponible en la siguiente fase')
        self.assertNotContains(response, '500.00')

    def test_day_closed_blocks_new_sale_and_additions(self):
        from apps.cash.models import BusinessDay
        from django.utils import timezone
        order = self.create_sale()
        BusinessDay.objects.filter(pk=self.day.pk).update(status='CLOSED', closed_at=timezone.now(), closed_by=self.user)
        self.assertEqual(self.post(order, 'agregar', product=self.product.pk).status_code, 401)


@override_settings(PASSWORD_HASHERS=["django.contrib.auth.hashers.MD5PasswordHasher"])
class CashSalesConcurrencyTests(TransactionTestCase):
    concurrent = CashWorkstationConcurrencyTests.concurrent

    def setUp(self):
        CashWorkstationConcurrencyTests.setUp(self)
        for user in self.users:
            user.user_permissions.add(*Permission.objects.filter(content_type__app_label__in=["orders", "payments", "cash"]))
        CashWorkstationConcurrencyTests.open_all(self)
        self.category = Category.objects.create(name="Bebidas", slug="bebidas")
        self.product = Product.objects.create(category=self.category, name="Gallo", slug="gallo", base_price=25,
            track_inventory=True, stock_quantity=1, preparation_route="AREA_BAR")
        self.table = VenueTable.objects.create(area=self.area, name="Mesa 12", capacity=4)

    def sale(self, client):
        result = client.post("/caja/venta-rapida/nueva/", HTTP_ACCEPT="application/json")
        order = TableOrder.objects.get(pk=int(result.json()["next"].split('/')[3]))
        self.assertEqual(client.post(f"/caja/orden/{order.pk}/pedido/agregar/", {"product": self.product.pk, "quantity": 1}, HTTP_ACCEPT="application/json").status_code, 200)
        token = client.post(f"/caja/orden/{order.pk}/cuenta/preparar/", HTTP_ACCEPT="application/json").json()["quote"]["token"]
        return order, token

    def test_two_stations_competing_for_last_stock_charge_only_winner(self):
        sales = [self.sale(client) for client in self.clients]
        results = self.concurrent([lambda c=c, o=o, t=t: c.post(f"/caja/orden/{o.pk}/cuenta/efectivo/", {"token": t, "received": "25"}, HTTP_ACCEPT="application/json") for c, (o, t) in zip(self.clients, sales)])
        self.assertCountEqual([r.status_code for r in results], [200, 409])
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 0)
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(CashMovement.objects.count(), 1)
        self.assertEqual(OrderLine.objects.filter(status="DRAFT").count(), 1)
        self.assertFalse(PreparationTicket.objects.exists())

    def test_simultaneous_cash_and_waiter_additions_preserve_separate_drafts(self):
        order = orders.open_table_order(self.table, self.admin)
        results = self.concurrent([
            lambda: self.clients[0].post(f"/caja/orden/{order.pk}/pedido/agregar/", {"product": self.product.pk, "quantity": 1}, HTTP_ACCEPT="application/json"),
            lambda: orders.add_product_to_order(order, self.product, 1, self.admin),
        ])
        self.assertEqual(results[0].status_code, 200)
        self.assertEqual(order.lines.count(), 2)
        self.assertEqual(order.lines.filter(draft_origin="").count(), 1)
        self.product.refresh_from_db(); self.assertEqual(self.product.stock_quantity, 1)

    def test_close_racing_cash_addition_never_adds_to_closed_order(self):
        order = orders.open_table_order(self.table, self.admin)
        def close():
            try:
                payments.close_order(order, self.admin)
                return "closed"
            except ValidationError:
                return "drafts"
        result, response = self.concurrent([close, lambda: self.clients[0].post(f"/caja/orden/{order.pk}/pedido/agregar/", {"product": self.product.pk, "quantity": 1}, HTTP_ACCEPT="application/json")])
        order.refresh_from_db()
        if result == "closed":
            self.assertEqual(response.status_code, 409)
            self.assertEqual(order.status, "CLOSED")
            self.assertFalse(order.lines.exists())
        else:
            self.assertEqual(response.status_code, 200)
            self.assertEqual(order.status, "OPEN")
            self.assertEqual(order.lines.get().status, "DRAFT")

    def test_duplicate_payment_in_parallel_consumes_once(self):
        client = self.clients[0]
        order, token = self.sale(client)
        duplicate = Client(); duplicate.cookies.update(client.cookies)
        results = self.concurrent([lambda c=c: c.post(f"/caja/orden/{order.pk}/cuenta/efectivo/", {"token": token, "received": "25"}, HTTP_ACCEPT="application/json") for c in (client, duplicate)])
        self.assertCountEqual([r.status_code for r in results], [200, 409])
        self.assertEqual(Payment.objects.count(), 1)
        self.assertEqual(InventoryMovement.objects.count(), 1)
