"""Explicit public contracts. Fields not listed here NEVER enter a payload.

Transport has no model introspection export, Django fixtures or automatic registration.
The shared codec only validates these reviewed allowlists against field types.
"""
from dataclasses import dataclass
from django.apps import apps

@dataclass(frozen=True)
class Entity:
    label: str
    authority: str
    fields: tuple
    children: tuple = ()
    schema_version: int = 1
    @property
    def model(self): return apps.get_model(self.label)
    @property
    def dependencies(self):
        return tuple(f.related_model._meta.label_lower for name in self.fields if (f:=self.model._meta.get_field(name)).is_relation)
    def serialize(self,obj):
        from .serializers import serialize_entity
        return serialize_entity(self,obj)
    def apply(self,event):
        from .appliers import apply_entity
        return apply_entity(self,event)

REGISTRY = {}
def register(label,authority,fields,children=''):
    REGISTRY[label] = Entity(label,authority,tuple(fields.split()),tuple(children.split()))

register('accounts.user','local','first_name last_name role is_active')
register('venues.area','local','name slug description is_active sort_order created_at updated_at')
register('venues.zone','local','area name slug description is_active sort_order created_at updated_at')
register('tables.venuetable','local','area zone name capacity is_active operational_status reservable_web sort_order layout_x layout_y layout_width layout_height layout_shape created_at updated_at')
register('catalog.category','local','name slug description sort_order is_active created_at updated_at')
register('catalog.product','local','category name slug barcode base_price is_active visible_in_pos track_inventory minimum_stock preparation_route is_combo created_at updated_at','area_prices modifier_groups combo_components')
register('catalog.productareaprice','local','product area price created_at updated_at')
register('catalog.modifiergroup','local','product name selection_type min_selections max_selections sort_order is_required is_active','options')
register('catalog.modifieroption','local','group name price_delta sort_order is_active')
register('catalog.combocomponent','local','combo component quantity sort_order')
register('cash.businessday','local','business_date status opened_at opened_by closed_at closed_by reopened_at reopened_by reopen_reason created_at updated_at','reopens')
register('cash.businessdayreopen','local','business_day reopened_by reopened_at reason previous_closed_at previous_closed_by')
register('cash.cashregister','local','name code area is_active created_at updated_at')
register('cash.cashsession','local','business_day register cashier opened_by status opening_float opened_at closed_at counted_cash counted_at counted_by expected_cash_at_close difference closing_reason closed_by created_at updated_at','movements handoffs')
register('orders.tableorder','local','order_type customer_alias cash_session fulfilled_at reservation_released_at business_day primary_table area responsible_waiter opened_by status billing_mode general_note merged_into opened_at closed_at created_at updated_at','table_links subaccounts lines payments adjustments reservation_credits')
register('orders.ordertablelink','local','order table created_at released_at')
register('orders.subaccount','local','order name status created_at closed_at')
register('orders.orderline','local','fulfillment_mode order subaccount product product_name_snapshot is_combo_snapshot quantity unit_price base_unit_price notes status created_by source_line created_at updated_at','modifiers components')
register('orders.orderlinemodifier','local','order_line modifier_option option_name_snapshot price_delta_snapshot')
register('orders.orderlinecomponent','local','order_line product quantity_per_unit name_snapshot route_snapshot stock_deducted')
register('payments.payment','local','order subaccount method status amount recorded_by created_at confirmed_at confirmed_by reference notes metadata cash_handoff_status','allocations refunds cash_handoff')
register('payments.paymentallocation','local','order_line unit_number quantity amount payment')
register('payments.orderadjustment','local','order subaccount adjustment_type amount reason authorized_by created_at','allocations')
register('payments.adjustmentallocation','local','order_line unit_number quantity amount adjustment')
register('payments.paymentrefund','local','payment amount reason created_by return_to_inventory created_at','allocations')
register('payments.refundallocation','local','refund payment_allocation amount quantity')
register('cash.cashhandoff','local','payment waiter cash_session amount status received_by created_at received_at')
register('cash.cashmovement','local','cash_session movement_type amount reason created_by approved_by payment handoff refund created_at')
register('inventory.inventorymovement','local','product movement_type quantity_delta stock_before stock_after reason user created_at')
# Reservation credit is operational ledger data; needed to preserve balances in reports.
register('reservations.reservationcredit','local','order payment amount created_by created_at','allocations')
register('reservations.reservationcreditallocation','local','credit order_line unit_number amount')
register('reservations.reservationsettings','cloud','reservations_enabled default_duration_minutes public_hold_minutes payment_window_minutes advance_payment_enabled advance_payment_type advance_payment_value advance_payment_application')
register('reservations.reservation','cloud','public_code reservation_type table area customer_name customer_phone reservation_date start_time starts_at ends_at duration_minutes party_size status payment_required payment_type payment_value payment_base_amount payment_amount payment_application hold_expires_at payment_expires_at approved_at rejected_at rejection_reason arrival_confirmed_at cancelled_at cancellation_reason no_show_at no_show_reason created_at updated_at','payment')
register('reservations.reservationpayment','cloud','reservation method amount reference status submitted_at reviewed_at rejection_reason created_at')
register('events.eventsettings','cloud','purchase_hold_minutes payment_window_minutes transfer_instructions')
register('events.event','cloud','name slug artist_name description starts_at ends_at status ticket_sales_enabled maximum_capacity published_at created_by cancellation_reason created_at updated_at','ticket_types table_configurations')
register('events.eventtickettype','cloud','event name price capacity sale_starts_at sale_ends_at max_per_purchase sort_order is_active is_courtesy_type created_at updated_at')
register('events.eventtableconfiguration','cloud','event table enabled capacity_snapshot ticket_type cover_per_person created_at updated_at')
register('core.banktransfersettings','cloud','enabled bank_name account_name account_number instructions')

# Purchases, their payments, buyers, proofs and raw EventTicket tokens stay on cloud.
# Access permissions travel solely through the signed schema-1 snapshot channel.
SPECIAL_AUTHORITIES = {'sync.conflict':'cloud','inventory.stock_snapshot':'local','access.scan':'local','reservation.arrived':'local','events.access_snapshot':'cloud'}

def authority(entity_type):
    return REGISTRY[entity_type].authority if entity_type in REGISTRY else SPECIAL_AUTHORITIES.get(entity_type)
