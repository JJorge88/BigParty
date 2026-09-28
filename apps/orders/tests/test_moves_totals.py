from unittest.mock import patch

from django.core.exceptions import ValidationError

from apps.inventory.models import InventoryMovement
from apps.orders import services as s
from apps.orders.models import TableOrder, OrderLine
from apps.tables.models import VenueTable
from .base import OrdersTestCase


class SubaccountMoveAndTotalTests(OrdersTestCase):
    def split_setup(self):
        order = self.open(split=True)
        first = s.create_subaccount(order, "Jorge", self.user)
        second = s.create_subaccount(order, "Carlos", self.user)
        line = s.add_product_to_order(order, self.product, 4, self.user, subaccount=first)
        return order, first, second, line

    def test_partial_draft_move_preserves_values_and_totals(self):
        order, first, second, line = self.split_setup()
        moved = s.move_line_to_subaccount(line, second, self.other_user, quantity=1)
        line.refresh_from_db()
        self.assertEqual(line.quantity, 3)
        self.assertEqual(moved.quantity, 1)
        self.assertEqual(moved.unit_price, line.unit_price)
        self.assertEqual(moved.source_line, line)
        self.assertEqual(s.get_subaccount_pending_total(first), 75)
        self.assertEqual(s.get_subaccount_total(second), 25)
        self.assertEqual(s.get_order_pending_total(order), 100)
        self.assertEqual(s.get_order_committed_total(order), 0)
        self.assertEqual(s.get_order_grand_total(order), 100)

    def test_full_move_does_not_clone(self):
        order, first, second, line = self.split_setup()
        result = s.move_line_to_subaccount(line, second, self.user)
        self.assertEqual(result.pk, line.pk)
        self.assertEqual(order.lines.count(), 1)
        self.assertEqual(s.get_subaccount_total(first), 0)
        self.assertEqual(s.get_subaccount_total(second), 100)

    def test_partial_sent_move_keeps_ticket_and_restores_exact_stock_on_cancellation(self):
        order, first, second, line = self.split_setup()
        ticket = s.send_order(order, self.user)
        item = ticket.items.get()
        moved = s.move_line_to_subaccount(line, second, self.user, quantity=1)
        item.refresh_from_db()
        self.assertEqual(item.quantity, 4)
        self.assertEqual(item.order_line_id, line.pk)
        self.assertEqual(order.tickets.count(), 1)
        self.assertEqual(InventoryMovement.objects.count(), 1)
        self.assertEqual(s.get_subaccount_committed_total(first), 75)
        self.assertEqual(s.get_subaccount_committed_total(second), 25)
        s.cancel_sent_line(moved, self.user, "Error en una unidad")
        s.cancel_sent_line(line, self.user, "Error en las restantes")
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 100)
        self.assertEqual(s.get_order_total(order), 0)

    def test_invalid_destination_closed_accounts_and_excess_quantity(self):
        order, first, second, line = self.split_setup()
        other = self.open(self.destination, split=True)
        foreign = s.create_subaccount(other, "Otra", self.user)
        with self.assertRaises(ValidationError):
            s.move_line_to_subaccount(line, foreign, self.user)
        with self.assertRaises(ValidationError):
            s.move_line_to_subaccount(line, second, self.user, quantity=5)
        second.status = "CLOSED"
        second.save()
        with self.assertRaises(ValidationError):
            s.move_line_to_subaccount(line, second, self.user)
        second.status = "OPEN"
        second.save()
        first.status = "CLOSED"
        first.save()
        with self.assertRaises(ValidationError):
            s.move_line_to_subaccount(line, second, self.user)

    def test_pending_committed_and_cancelled_totals(self):
        order = self.open()
        line = s.add_product_to_order(order, self.product, 2, self.user)
        s.send_order(order, self.user)
        s.add_product_to_order(order, self.product, 1, self.user)
        self.assertEqual(s.get_order_pending_total(order), 25)
        self.assertEqual(s.get_order_committed_total(order), 50)
        self.assertEqual(s.get_order_grand_total(order), 75)
        s.cancel_sent_line(line, self.user, "Error")
        self.assertEqual(s.get_order_total(order), 25)


class TableMoveAndMergeTests(OrdersTestCase):
    def test_move_frees_previous_table_and_keeps_ticket_snapshot(self):
        order = self.open()
        s.add_product_to_order(order, self.product, 1, self.user)
        ticket = s.send_order(order, self.user)
        s.move_order_to_table(order, self.destination, self.other_user)
        self.assertEqual(s.get_operational_table_state(self.table), "AVAILABLE")
        self.assertEqual(s.get_active_order_for_table(self.destination), order)
        ticket.refresh_from_db()
        self.assertEqual(ticket.table_name_snapshot, "Mesa 01")
        s.add_product_to_order(order, self.product, 1, self.user)
        addition = s.send_order(order, self.user)
        self.assertEqual(addition.table_name_snapshot, "Mesa 02")
        s.move_order_to_table(order, self.table, self.user)
        self.assertEqual(s.get_active_order_for_table(self.table), order)

    def test_move_rejects_occupied_out_of_service_and_cross_area(self):
        order = self.open()
        self.open(self.destination)
        with self.assertRaises(ValidationError):
            s.move_order_to_table(order, self.destination, self.user)
        other = VenueTable.objects.create(area=self.other_area, name="Otra", capacity=4)
        with self.assertRaises(ValidationError):
            s.move_order_to_table(order, other, self.user)
        outside = VenueTable.objects.create(area=self.area, name="Fuera", capacity=4, operational_status="OUT_OF_SERVICE")
        with self.assertRaises(ValidationError):
            s.move_order_to_table(order, outside, self.user)

    def test_join_free_table_resolves_same_order_and_retains_one_primary(self):
        order = self.open()
        s.join_table_to_order(order, self.destination, self.user)
        self.assertEqual(s.get_active_order_for_table(self.destination), order)
        self.assertEqual(s.get_operational_table_state(self.destination), "OCCUPIED")
        self.assertEqual(sum(link.is_primary for link in order.table_links.all()), 1)
        with self.assertRaises(ValidationError):
            self.open(self.destination)

    def test_merge_moves_subaccounts_lines_notes_and_timeline_preserving_tickets(self):
        primary = self.open()
        secondary = self.open(self.destination, split=True)
        account = s.create_subaccount(secondary, "Jorge", self.other_user)
        line = s.add_product_to_order(secondary, self.product, 2, self.other_user, subaccount=account)
        ticket = s.send_order(secondary, self.other_user)
        s.update_order_note(secondary, "Cumpleaños", self.other_user)
        original_ticket = (ticket.order_id, ticket.sequence_number, ticket.table_name_snapshot)
        s.merge_orders(primary, secondary, self.user)
        primary.refresh_from_db()
        secondary.refresh_from_db()
        line.refresh_from_db()
        account.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(primary.billing_mode, "SPLIT")
        self.assertEqual(secondary.status, "MERGED")
        self.assertEqual(secondary.merged_into, primary)
        self.assertEqual((line.order, account.order), (primary, primary))
        self.assertIn("Cumpleaños", primary.general_note)
        self.assertEqual((ticket.order_id, ticket.sequence_number, ticket.table_name_snapshot), original_ticket)
        self.assertEqual(s.get_active_order_for_table(self.table), primary)
        self.assertEqual(s.get_active_order_for_table(self.destination), primary)
        self.assertIn(ticket, s.get_order_tickets(primary))
        self.assertTrue(s.get_order_timeline(primary).filter(origin_order=secondary, activity_type="ORDER_SENT").exists())
        self.assertEqual(s.get_order_total(primary), 50)
        self.assertEqual(s.get_order_total(secondary), 0)
        self.assertEqual(TableOrder.objects.count(), 2)

    def test_merge_two_single_orders_preserves_single_mode(self):
        primary = self.open()
        secondary = self.open(self.destination)
        s.add_product_to_order(primary, self.product, 1, self.user)
        s.add_product_to_order(secondary, self.product, 2, self.user)
        result = s.merge_orders(primary, secondary, self.user)
        self.assertEqual(result.billing_mode, "SINGLE")
        self.assertEqual(result.lines.count(), 2)
        self.assertEqual(s.get_order_total(result), 75)
        s.send_order(result, self.user)
        self.product.refresh_from_db()
        self.assertEqual(self.product.stock_quantity, 97)

    def test_merge_rejects_same_order_other_area_inactive_and_closed_subaccount(self):
        primary = self.open()
        with self.assertRaises(ValidationError):
            s.merge_orders(primary, primary, self.user)
        table = VenueTable.objects.create(area=self.other_area, name="Otra", capacity=4)
        other = self.open(table)
        with self.assertRaises(ValidationError):
            s.merge_orders(primary, other, self.user)
        secondary = self.open(self.destination, split=True)
        account = s.create_subaccount(secondary, "Cerrada", self.user)
        account.status = "CLOSED"
        account.save()
        with self.assertRaises(ValidationError):
            s.merge_orders(primary, secondary, self.user)

    def test_merge_failure_rolls_back_all_transfers(self):
        primary = self.open()
        secondary = self.open(self.destination)
        line = s.add_product_to_order(secondary, self.product, 1, self.user)
        with patch("apps.orders.services._log", side_effect=RuntimeError("audit")):
            with self.assertRaises(RuntimeError):
                s.merge_orders(primary, secondary, self.user)
        line.refresh_from_db()
        secondary.refresh_from_db()
        self.assertEqual(line.order, secondary)
        self.assertEqual(secondary.status, "OPEN")
        self.assertEqual(s.get_active_order_for_table(self.destination), secondary)

    def test_multitable_move_does_not_implicitly_unmerge(self):
        order = self.open()
        s.join_table_to_order(order, self.destination, self.user)
        other = VenueTable.objects.create(area=self.area, name="Otra", capacity=4)
        with self.assertRaises(ValidationError):
            s.move_order_to_table(order, other, self.user)
        self.assertEqual(order.table_links.filter(released_at__isnull=True).count(), 2)
