from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction, connection

from apps.audit.models import AuditLog
from apps.catalog.models import ModifierGroup, ModifierOption, Product
from apps.catalog.services import update_base_price, update_area_price
from apps.inventory.models import InventoryMovement
from apps.orders.models import TableOrder, OrderLine, OrderTableLink, SubAccount
from apps.orders import services as s
from .base import OrdersTestCase


class OpeningAndAccountTests(OrdersTestCase):
    def test_opening_assigns_waiter_actor_area_and_primary(self):
        order = s.open_table_order(self.table, self.user, responsible_waiter=self.other_user)
        self.assertEqual(order.status, "OPEN")
        self.assertEqual(order.responsible_waiter, self.other_user)
        self.assertEqual(order.opened_by, self.user)
        self.assertEqual(order.area, self.area)
        self.assertEqual(order.order_number, f"{order.pk:06d}")
        self.assertTrue(order.table_links.get().is_primary)
        self.assertEqual(s.get_active_order_for_table(self.table), order)
        self.assertEqual(s.get_operational_table_state(self.table), "OCCUPIED")
        self.assertEqual(order.activities.get().activity_type, "OPENED")

    def test_unavailable_table_rejected(self):
        for field, value in (("is_active", False), ("operational_status", "OUT_OF_SERVICE")):
            self.table.refresh_from_db()
            setattr(self.table, field, value)
            self.table.save()
            with self.subTest(field=field), self.assertRaises(ValidationError):
                self.open()
            self.assertEqual(s.get_operational_table_state(self.table), "OUT_OF_SERVICE")
            setattr(self.table, field, True if field == "is_active" else "ACTIVE")
            self.table.save()

    def test_double_opening_rejected(self):
        self.open()
        with self.assertRaises(ValidationError):
            self.open()
        self.assertEqual(TableOrder.objects.count(), 1)

    def test_permissions_are_explicit_not_role_based(self):
        user = get_user_model().objects.create_user(username="waiter", role="MESERO")
        with self.assertRaises(PermissionDenied):
            s.open_table_order(self.table, user)
        user.user_permissions.add(Permission.objects.get(codename="open_table_order"))
        user = get_user_model().objects.get(pk=user.pk)
        order = s.open_table_order(self.table, user)
        with self.assertRaises(PermissionDenied):
            s.add_product_to_order(order, self.product, 1, user)

    def test_multiple_duplicate_named_subaccounts_are_allowed(self):
        order = self.open(split=True)
        first = s.create_subaccount(order, "Jorge", self.user)
        second = s.create_subaccount(order, "Jorge", self.user)
        self.assertNotEqual(first.pk, second.pk)
        self.assertEqual(order.activities.filter(activity_type="SUBACCOUNT_CREATED").count(), 2)

    def test_subaccounts_require_split_and_nonempty_name(self):
        order = self.open()
        with self.assertRaises(ValidationError):
            s.create_subaccount(order, "Jorge", self.user)
        order = s.change_billing_mode(order, "SPLIT", self.user)
        with self.assertRaises(ValidationError):
            s.create_subaccount(order, "  ", self.user)
        s.create_subaccount(order, "Jorge", self.user)
        with self.assertRaises(ValidationError):
            s.change_billing_mode(order, "SINGLE", self.user)

    def test_closed_account_rejects_operations(self):
        order = self.open(split=True)
        account = s.create_subaccount(order, "Jorge", self.user)
        account.status = "CLOSED"
        account.save()
        with self.assertRaises(ValidationError):
            s.add_product_to_order(order, self.product, 1, self.user, subaccount=account)
        order.status = "CLOSED"
        order.save()
        with self.assertRaises(ValidationError):
            s.create_subaccount(order, "Otra", self.user)

    def test_database_protects_table_links_and_subaccount_consistency(self):
        first = self.open(split=True)
        second = self.open(self.destination, split=True)
        account = s.create_subaccount(second, "Otra", self.user)
        line = s.add_product_to_order(first, self.product, 1, self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderTableLink.objects.create(order=second, table=self.table)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrderLine.objects.filter(pk=line.pk).update(subaccount=account)
            connection.check_constraints()


class DraftAndPriceTests(OrdersTestCase):
    def test_draft_has_snapshot_area_price_without_consuming_stock(self):
        order = self.open()
        update_area_price(self.product, self.area, 30, user=self.user)
        line = s.add_product_to_order(order, self.product, 2, self.other_user)
        self.assertEqual(line.unit_price, Decimal("30.00"))
        self.assertEqual(line.subtotal, Decimal("60.00"))
        self.assertEqual(line.created_by, self.other_user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        update_area_price(self.product, self.area, 40, user=self.user)
        line.refresh_from_db()
        self.assertEqual(line.unit_price, Decimal("30.00"))

    def test_modifiers_validate_groups_and_capture_snapshots(self):
        order = self.open()
        group = ModifierGroup.objects.create(product=self.product, name="Preparación", is_required=True, min_selections=1)
        option = ModifierOption.objects.create(group=group, name="Extra", price_delta=10)
        with self.assertRaises(ValidationError):
            s.add_product_to_order(order, self.product, 1, self.user)
        line = s.add_product_to_order(order, self.product, 2, self.user, modifier_option_ids=[option.pk])
        self.assertEqual(line.unit_price, Decimal("35.00"))
        self.assertEqual(line.subtotal, Decimal("70.00"))
        option.name = "Otro nombre"
        option.price_delta = 20
        option.save()
        self.assertEqual(line.modifiers.get().option_name_snapshot, "Extra")
        self.assertEqual(line.modifiers.get().price_delta_snapshot, Decimal("10.00"))

    def test_invalid_modifier_duplicates_foreign_inactive_and_maximum(self):
        order = self.open()
        group = ModifierGroup.objects.create(product=self.product, name="Opciones")
        first = ModifierOption.objects.create(group=group, name="Uno")
        second = ModifierOption.objects.create(group=group, name="Dos")
        third = ModifierOption.objects.create(group=group, name="Inactivo", is_active=False)
        for ids in ([first.pk, first.pk], [first.pk, second.pk], [third.pk], [999999]):
            with self.subTest(ids=ids), self.assertRaises(ValidationError):
                s.add_product_to_order(order, self.product, 1, self.user, modifier_option_ids=ids)
        group.is_active = False
        group.save()
        with self.assertRaises(ValidationError):
            s.add_product_to_order(order, self.product, 1, self.user, modifier_option_ids=[first.pk])

    def test_equivalent_drafts_group_and_sent_lines_do_not(self):
        order = self.open()
        ids = [s.add_product_to_order(order, self.product, 1, self.user).pk for _ in range(4)]
        self.assertEqual(len(set(ids)), 1)
        line = order.lines.get()
        self.assertEqual(line.quantity, 4)
        s.send_order(order, self.user)
        later = s.add_product_to_order(order, self.product, 1, self.user)
        self.assertNotEqual(later.pk, line.pk)
        line.refresh_from_db()
        self.assertEqual(line.quantity, 4)

    def test_different_note_price_or_subaccount_do_not_group(self):
        order = self.open(split=True)
        first = s.create_subaccount(order, "Uno", self.user)
        second = s.create_subaccount(order, "Dos", self.user)
        s.add_product_to_order(order, self.product, 1, self.user, subaccount=first)
        s.add_product_to_order(order, self.product, 1, self.user, subaccount=second)
        s.add_product_to_order(order, self.product, 1, self.user, subaccount=first, notes="Sin hielo")
        update_base_price(self.product, 26, user=self.user)
        s.add_product_to_order(order, self.product, 1, self.user, subaccount=first)
        self.assertEqual(order.lines.count(), 4)

    def test_quantity_and_product_availability(self):
        order = self.open()
        for quantity in (0, -1, True, 1.5):
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                s.add_product_to_order(order, self.product, quantity, self.user)
        self.product.stock_quantity = 0
        self.product.save()
        with self.assertRaises(ValidationError):
            s.add_product_to_order(order, self.product, 1, self.user)

    def test_draft_corrections_and_removal_preserve_history(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 2, self.user)
        s.increase_draft_line(line, self.user)
        s.decrease_draft_line(line, self.user)
        line = s.update_draft_line_note(line, "Sin salsa", self.user)
        self.assertEqual(line.quantity, 2)
        self.assertEqual(line.notes, "Sin salsa")
        s.decrease_draft_line(line, self.user, quantity=2)
        line.refresh_from_db()
        self.assertEqual(line.status, "CANCELLED")
        self.assertEqual(order.lines.count(), 1)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        self.assertEqual(s.get_order_total(order), 0)

    def test_sent_line_cannot_be_corrected_as_draft(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 1, self.user)
        s.send_order(order, self.user)
        for action in (s.increase_draft_line, s.decrease_draft_line, s.remove_draft_line):
            with self.subTest(action=action), self.assertRaises(ValidationError):
                action(line, self.user)

    def test_notes_and_timeline_capture_other_operator(self):
        order = self.open()
        s.update_order_note(order, "Cumpleaños", self.other_user)
        event = s.get_order_timeline(order).first()
        self.assertEqual(event.user, self.other_user)
        self.assertEqual(event.activity_type, "NOTE_UPDATED")
        self.assertEqual(event.metadata["after"], "Cumpleaños")

    def test_audit_failure_rolls_back_added_line(self):
        order = self.open()
        with patch("apps.orders.services.AuditLog.objects.create", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                s.add_product_to_order(order, self.product, 1, self.user)
        self.assertEqual(order.lines.count(), 0)


class SendingAndCancellationTests(OrdersTestCase):
    def test_send_creates_bar_ticket_and_sale_once(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 3, self.user)
        ticket = s.send_order(order, self.other_user)
        self.assertEqual(ticket.ticket_type, "NEW")
        self.assertEqual(ticket.sequence_number, 1)
        item = ticket.items.get()
        self.assertEqual(item.route, "AREA_BAR")
        self.assertEqual(item.area, self.area)
        self.assertEqual(item.quantity, 3)
        movement = InventoryMovement.objects.get()
        self.assertEqual(movement.movement_type, "SALE")
        self.assertEqual(movement.quantity_delta, -3)
        self.assertEqual(movement.metadata, {"order_id": order.pk, "line_id": line.pk, "table": self.table.pk})
        self.assertIsNone(s.send_order(order, self.user))
        self.assertEqual(InventoryMovement.objects.count(), 1)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 97)

    def test_kitchen_and_none_routes(self):
        order = self.open()
        self.product.preparation_route = "KITCHEN"
        self.product.save()
        s.add_product_to_order(order, self.product, 1, self.user)
        self.assertEqual(s.send_order(order, self.user).items.get().route, "KITCHEN")
        other = Product.objects.create(category=self.category, name="Sin comanda", slug="none", preparation_route="NONE")
        line = s.add_product_to_order(order, other, 1, self.user)
        self.assertIsNone(s.send_order(order, self.user))
        line.refresh_from_db()
        self.assertEqual(line.status, "SENT")
        self.assertEqual(order.tickets.count(), 1)

    def test_later_send_is_addition(self):
        order = self.open()
        s.add_product_to_order(order, self.product, 1, self.user)
        s.send_order(order, self.user)
        s.add_product_to_order(order, self.product, 2, self.user)
        ticket = s.send_order(order, self.user)
        self.assertEqual((ticket.ticket_type, ticket.sequence_number), ("ADDITION", 2))

    def test_combo_components_are_frozen_and_consumed(self):
        combo, energy = self.combo()
        order = self.open()
        line = s.add_product_to_order(order, combo, 2, self.user)
        self.assertEqual(line.unit_price, 100)
        self.assertEqual(len(s.get_line_combo_components(line)), 2)
        combo.combo_components.filter(component=energy).update(quantity=7)
        ticket = s.send_order(order, self.user)
        energy.refresh_from_db()
        self.assertEqual(energy.stock_quantity, 22)
        self.assertEqual(ticket.items.count(), 1)
        self.assertEqual(order.lines.count(), 1)
        s.cancel_sent_line(line, self.user, "Error")
        energy.refresh_from_db()
        self.assertEqual(energy.stock_quantity, 30)

    def test_insufficient_combined_stock_reverts_entire_send(self):
        combo, energy = self.combo()
        order = self.open()
        s.add_product_to_order(order, combo, 5, self.user)
        # Oculto no se vende directamente; otra línea del mismo combo no se agrupa por nota.
        s.add_product_to_order(order, combo, 5, self.user, notes="Otra ronda")
        with self.assertRaises(ValidationError):
            s.send_order(order, self.user)
        self.assertEqual(order.lines.filter(status="DRAFT").count(), 2)
        self.assertEqual(order.tickets.count(), 0)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        energy.refresh_from_db()
        self.assertEqual(energy.stock_quantity, 30)

    def test_stock_is_revalidated_after_draft(self):
        order = self.open()
        s.add_product_to_order(order, self.product, 2, self.user)
        self.product.stock_quantity = 1
        self.product.save()
        with self.assertRaises(ValidationError):
            s.send_order(order, self.user)

    def test_send_failure_after_movement_rolls_back_everything(self):
        order = self.open()
        s.add_product_to_order(order, self.product, 2, self.user)
        with patch("apps.orders.services._ticket", side_effect=RuntimeError("ticket")):
            with self.assertRaises(RuntimeError):
                s.send_order(order, self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
        self.assertEqual(InventoryMovement.objects.count(), 0)
        self.assertEqual(order.lines.get().status, "DRAFT")

    def test_sent_note_creates_update_without_stock_change(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 2, self.user, notes="Original")
        first_ticket = s.send_order(order, self.user)
        s.update_sent_line_note(line, "Sin salsa", self.other_user)
        self.assertEqual(first_ticket.items.get().notes_snapshot, "Original")
        update = order.tickets.get(ticket_type="UPDATE")
        self.assertEqual(update.items.get().notes_snapshot, "Sin salsa")
        self.assertEqual(InventoryMovement.objects.count(), 1)

    def test_cancellation_requires_permission_reason_and_is_not_repeatable(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 2, self.user)
        s.send_order(order, self.user)
        user = get_user_model().objects.create_user(username="manager", role="GERENTE")
        with self.assertRaises(PermissionDenied):
            s.cancel_sent_line(line, user, "Error")
        with self.assertRaises(ValidationError):
            s.cancel_sent_line(line, self.user, " ")
        s.cancel_sent_line(line, self.user, "Error de captura")
        with self.assertRaises(ValidationError):
            s.cancel_sent_line(line, self.user, "Otra vez")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
        self.assertEqual(InventoryMovement.objects.get(movement_type="CANCELLATION_RETURN").quantity_delta, 2)
        self.assertEqual(order.tickets.get(ticket_type="CANCELLATION").items.get().quantity, 2)
        self.assertTrue(AuditLog.objects.filter(action="orders.line_cancelled").exists())

    def test_tracking_cannot_be_disabled_before_cancellation_return(self):
        self.product.stock_quantity = 1
        self.product.save()
        order = self.open()
        line = s.add_product_to_order(order, self.product, 1, self.user)
        s.send_order(order, self.user)
        self.product.refresh_from_db()
        self.product.track_inventory = False
        with self.assertRaises(ValidationError):
            self.product.save()
        s.cancel_sent_line(line, self.user, "Error")
        self.product.refresh_from_db()
        self.assertTrue(self.product.track_inventory)
        self.assertEqual(self.product.stock_quantity, 1)
