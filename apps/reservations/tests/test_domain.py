from datetime import timedelta, time
from decimal import Decimal as D
from io import StringIO
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.utils import timezone
from apps.audit.models import AuditLog
from apps.cash.models import BusinessDay
from apps.cash.services import open_business_day
from apps.catalog.models import Category, Product
from apps.orders import services as orders
from apps.orders.queries import get_operational_table_state
from apps.orders.models import TableOrder
from apps.payments import services as payments
from apps.payments.queries import get_financial_summary, get_receipt_data, prefetch_financials
from apps.reservations import services as s
from apps.reservations.models import Reservation, ReservationSettings, ReservationPayment
from apps.reservations.queries import get_settings, get_available_tables
from apps.reservations.credits import credit_summary
from .base import ReservationCase, proof


class SettingsAndAvailabilityTests(ReservationCase):
    def test_defaults(self):
        config = get_settings()
        self.assertEqual((config.default_duration_minutes, config.public_hold_minutes, config.payment_window_minutes), (180, 15, 15))
        self.assertFalse(config.advance_payment_enabled)

    def test_configuration_validation_and_permission(self):
        for values in ({'default_duration_minutes': 0}, {'advance_payment_enabled': True, 'advance_payment_value': 0},
                       {'advance_payment_type': 'PERCENTAGE', 'advance_payment_value': 101}):
            with self.assertRaises(ValidationError):
                s.configure_reservations(self.manager, **values)
        with self.assertRaises(PermissionDenied):
            s.configure_reservations(self.waiter, reservations_enabled=False)
        s.configure_reservations(self.manager, reservations_enabled=False)
        with self.assertRaises(ValidationError):
            self.request()

    def available(self, start=None, duration=180, **kwargs):
        start = start or self.start
        return get_available_tables(start.date(), start.time().replace(tzinfo=None), duration, **kwargs)

    def test_available_capacity_and_area(self):
        self.assertIn(self.table, self.available(party_size=4, area=self.area))
        self.assertNotIn(self.table, self.available(party_size=7))
        with self.assertRaises(ValidationError):
            self.available(party_size=0)

    def test_excludes_inactive_out_of_service_and_non_web(self):
        for field, value in [('is_active', False), ('operational_status', 'OUT_OF_SERVICE'), ('reservable_web', False)]:
            original = getattr(self.table, field)
            setattr(self.table, field, value); self.table.save()
            self.assertNotIn(self.table, self.available())
            setattr(self.table, field, original); self.table.save()
        self.area.is_active = False; self.area.save()
        self.assertNotIn(self.table, self.available())

    def test_overlap_boundaries_and_midnight(self):
        start = self.start.replace(hour=23, minute=30)
        self.request(start=start)
        self.assertNotIn(self.table, self.available(start + timedelta(minutes=90)))
        self.assertIn(self.table, self.available(start + timedelta(minutes=180)))
        self.assertIn(self.table, self.available(start - timedelta(minutes=180)))
        with self.assertRaises(ValidationError):
            self.request(start=start + timedelta(minutes=179))

    def test_expired_holds_do_not_block_even_without_command(self):
        row = self.request()
        Reservation.objects.filter(pk=row.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertIn(self.table, self.available())
        self.request()

    def test_cancelled_rejected_and_no_show_release(self):
        row = self.request()
        s.reject_reservation(row, self.manager, 'Sin disponibilidad')
        self.assertIn(self.table, self.available())
        row = self.confirmed()
        s.cancel_reservation(row, self.manager, 'Cambio de planes')
        self.assertIn(self.table, self.available())

    def test_public_tokens_and_codes_not_sequential(self):
        first = self.request()
        second = self.request(start=self.start+timedelta(days=1))
        self.assertGreaterEqual(len(first.secure_token), 40)
        self.assertNotEqual(first.secure_token, second.secure_token)
        self.assertRegex(first.public_code, r'^BP-R-[A-Z2-9]{10}$')
        self.assertIsNone(first.created_by)
        self.assertEqual(first.status, 'PENDING_REVIEW')
        self.assertAlmostEqual((first.hold_expires_at-timezone.now()).total_seconds(), 900, delta=3)
        self.assertFalse(BusinessDay.objects.exists())

    def test_invalid_name_phone_past_and_party(self):
        for name, phone, start, party in [('', '+50255555555', self.start, 2), ('Ana', '5555', self.start, 2),
                    ('Ana', '+50255555555', self.start-timedelta(days=2), 2), ('Ana', '+50255555555', self.start, 7)]:
            with self.assertRaises(ValidationError):
                s.create_public_reservation_request(self.table,name,phone,start.date(),start.time().replace(tzinfo=None),party)

    def test_internal_non_web_table_and_direct_confirmation(self):
        self.table.reservable_web=False; self.table.save()
        row=s.create_manual_reservation(self.table,'Ana','+50255555555',self.start.date(),time(20),3,self.manager,payment_required=False)
        self.assertEqual(row.status,'CONFIRMED')
        self.assertIsNone(row.hold_expires_at)
        self.assertEqual(row.created_by,self.manager)


class LifecycleTests(ReservationCase):
    def test_approve_without_payment(self):
        row = self.approve()
        self.assertEqual(row.status,'CONFIRMED')
        self.assertIsNone(row.payment_expires_at)
        self.assertEqual(row.approved_by,self.manager)
        with self.assertRaises(ValidationError):
            s.approve_reservation(row,self.manager)

    def test_approve_with_payment(self):
        row=self.approve(paid=True)
        self.assertEqual(row.status,'AWAITING_PAYMENT')
        self.assertEqual(row.payment_amount,D('300'))
        self.assertAlmostEqual((row.payment_expires_at-timezone.now()).total_seconds(),900,delta=3)

    def test_percentage_requires_explicit_base_and_rounds(self):
        row=self.request()
        with self.assertRaises(ValidationError):
            s.approve_reservation(row,self.manager,payment_required=True,payment_type='PERCENTAGE',payment_value=25)
        row=s.approve_reservation(row,self.manager,payment_required=True,payment_type='PERCENTAGE',payment_value=25,payment_base_amount='1200.02')
        self.assertEqual(row.payment_amount,D('300.01'))
        self.assertEqual(row.payment_base_amount,D('1200.02'))

    def test_permissions_not_inferred_from_role(self):
        row=self.request()
        self.revoke('approve_reservation')
        with self.assertRaises(PermissionDenied):
            self.approve(row)
        with self.assertRaises(PermissionDenied):
            s.reject_reservation(row,self.waiter,'No')

    def test_expired_request_cannot_approve(self):
        row=self.request()
        Reservation.objects.filter(pk=row.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        with self.assertRaises(ValidationError):
            self.approve(row)

    def test_reject_requires_reason_preserves_history(self):
        row=self.request()
        with self.assertRaises(ValidationError):
            s.reject_reservation(row,self.manager,' ')
        s.reject_reservation(row,self.manager,'Horario no disponible')
        row.refresh_from_db()
        self.assertEqual(row.status,'REJECTED')
        self.assertTrue(AuditLog.objects.filter(action='reservations.rejected',entity_id=str(row.pk)).exists())

    def test_amount_reference_and_public_proof_required(self):
        row=self.approve(paid=True)
        for amount,reference,file in [(299,'R',proof()),(300,None,proof()),(300,' ',proof()),(300,'R',None),('NaN','R',proof()),('300.001','R',proof())]:
            with self.assertRaises(ValidationError):
                s.submit_reservation_payment(row,amount,reference,file)
        self.assertFalse(ReservationPayment.objects.exists())

    def test_valid_image_formats(self):
        for format in ('JPEG','PNG','WEBP'):
            s.validate_proof(proof(format))

    def test_invalid_and_oversize_images(self):
        for file in [SimpleUploadedFile('fake.png',b'<script>bad</script>',content_type='image/png'),
                     SimpleUploadedFile('huge.png',b'x'*(5*1024*1024+1)),proof('GIF')]:
            with self.assertRaises(ValidationError):
                s.validate_proof(file)

    def test_submission_freezes_timer_and_confirm(self):
        row=self.approve(paid=True)
        payment=s.submit_reservation_payment(row,300,'R',proof())
        Reservation.objects.filter(pk=row.pk).update(payment_expires_at=timezone.now()-timedelta(days=1))
        self.assertEqual(s.expire_reservations('AWAITING_PAYMENT'),0)
        row=s.confirm_reservation_payment(payment,self.manager)
        self.assertEqual(row.status,'CONFIRMED')
        payment.refresh_from_db(); self.assertEqual(payment.status,'CONFIRMED')

    def test_no_late_or_duplicate_submission(self):
        row=self.approve(paid=True)
        with patch('apps.reservations.services.timezone.now',return_value=row.payment_expires_at):
            with self.assertRaises(ValidationError):
                s.submit_reservation_payment(row,300,'R',proof())
        s.submit_reservation_payment(row,300,'R',proof())
        with self.assertRaises(ValidationError):
            s.submit_reservation_payment(row,300,'R',proof())

    def test_payment_permissions_and_reject_release(self):
        row=self.approve(paid=True)
        payment=s.submit_reservation_payment(row,300,'R',proof())
        with self.assertRaises(PermissionDenied):
            s.confirm_reservation_payment(payment,self.waiter)
        with self.assertRaises(PermissionDenied):
            s.reject_reservation_payment(payment,self.waiter,'No recibido')
        with self.assertRaises(ValidationError):
            s.reject_reservation_payment(payment,self.manager,'')
        s.reject_reservation_payment(payment,self.manager,'No se encontró ingreso')
        row.refresh_from_db(); payment.refresh_from_db()
        self.assertEqual((row.status,payment.status),('REJECTED','REJECTED'))
        self.request()

    def test_cancellation_keeps_payment_requires_reason(self):
        row=self.confirmed(paid=True)
        with self.assertRaises(ValidationError):
            s.cancel_reservation(row,self.manager)
        with self.assertRaises(PermissionDenied):
            s.cancel_reservation(row,self.waiter,'Cambio')
        s.cancel_reservation(row,self.manager,'Cambio de planes')
        row.refresh_from_db()
        self.assertEqual(row.status,'CANCELLED')
        self.assertEqual(row.payment.status,'CONFIRMED')

    def test_no_show_explicit_and_permission(self):
        row=self.confirmed(paid=True)
        with self.assertRaises(ValidationError):
            s.mark_reservation_no_show(row,self.manager)
        with self.assertRaises(PermissionDenied):
            s.mark_reservation_no_show(row,self.waiter)
        with patch('apps.reservations.services.timezone.now',return_value=row.ends_at+timedelta(hours=1)):
            self.assertEqual(s.expire_reservations('AWAITING_PAYMENT'),0)
            row=s.mark_reservation_no_show(row,self.manager)
        self.assertEqual(row.status,'NO_SHOW')
        self.assertEqual(row.payment.status,'CONFIRMED')

    def test_commands_idempotent_audit_and_no_review_expiry(self):
        hold=self.request()
        Reservation.objects.filter(pk=hold.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        pending=self.approve(paid=True)
        Reservation.objects.filter(pk=pending.pk).update(payment_expires_at=timezone.now()-timedelta(seconds=1))
        review=self.approve(paid=True)
        s.submit_reservation_payment(review,300,'R',proof())
        Reservation.objects.filter(pk=review.pk).update(payment_expires_at=timezone.now()-timedelta(seconds=1))
        for _ in range(2):
            call_command('expire_reservation_holds',stdout=StringIO())
            call_command('expire_reservation_payments',stdout=StringIO())
        self.assertEqual(Reservation.objects.filter(status='EXPIRED').count(),2)
        self.assertEqual(AuditLog.objects.filter(action='reservations.expired').count(),2)
        review.refresh_from_db();self.assertEqual(review.status,'PAYMENT_REVIEW')


class ArrivalCreditTests(ReservationCase):
    def day(self):
        return open_business_day(self.admin)

    def arrive(self, paid=False, application='CREDIT'):
        self.day()
        return s.confirm_reservation_arrival(self.confirmed(paid=paid,application=application),self.manager,self.waiter)

    def consume(self,row,amount=800):
        category=Category.objects.create(name='Consumo',slug='consumo')
        product=Product.objects.create(category=category,name='Servicio',slug='servicio',base_price=amount,track_inventory=False)
        line=orders.add_product_to_order(row.order,product,1,self.admin)
        orders.send_order(row.order,self.admin)
        return line

    def test_arrival_requires_day_waiter_active_and_permission(self):
        row=self.confirmed()
        with self.assertRaises(ValidationError):
            s.confirm_reservation_arrival(row,self.manager,self.waiter)
        self.day()
        for waiter in (None,self.manager):
            with self.assertRaises(ValidationError):
                s.confirm_reservation_arrival(row,self.manager,waiter)
        self.waiter.is_active=False;self.waiter.save()
        with self.assertRaises(ValidationError):
            s.confirm_reservation_arrival(row,self.manager,self.waiter)
        with self.assertRaises(PermissionDenied):
            s.confirm_reservation_arrival(row,self.waiter,self.waiter)
        self.assertFalse(TableOrder.objects.exists())

    def test_arrival_opens_once_without_extra_order_permission(self):
        row=self.arrive()
        self.assertFalse(self.manager.has_perm('orders.open_table_order'))
        self.assertEqual(row.status,'ARRIVED')
        self.assertEqual(row.order.responsible_waiter,self.waiter)
        self.assertEqual(row.order.opened_by,self.manager)
        self.assertEqual(row.order.billing_mode,'SINGLE')
        self.assertEqual(get_operational_table_state(self.table),'OCCUPIED')
        with self.assertRaises(ValidationError):
            s.confirm_reservation_arrival(row,self.manager,self.waiter)
        self.assertEqual(TableOrder.objects.count(),1)

    def test_busy_or_disabled_table_rejects_arrival(self):
        self.day();row=self.confirmed()
        order=orders.open_table_order(self.table,self.admin)
        with self.assertRaises(ValidationError):
            s.confirm_reservation_arrival(row,self.manager,self.waiter)
        self.assertEqual(TableOrder.objects.count(),1)

    def test_reserved_state_and_ordinary_open_blocked(self):
        self.day(); row=self.confirmed()
        with patch('apps.reservations.queries.timezone.now',return_value=row.starts_at+timedelta(minutes=1)):
            self.assertEqual(get_operational_table_state(self.table),'RESERVED')
            with self.assertRaises(ValidationError):
                orders.open_table_order(self.table,self.admin)
        self.table.operational_status='OUT_OF_SERVICE';self.table.save()
        self.assertEqual(get_operational_table_state(self.table),'OUT_OF_SERVICE')

    def test_credit_800_minus_300_equals_500_without_fake_payment(self):
        row=self.arrive(paid=True)
        self.assertEqual(credit_summary(row.order)['remaining'],D('300'))
        line=self.consume(row)
        summary=get_financial_summary(row.order)
        self.assertEqual((summary['gross_total'],summary['charge_total'],summary['confirmed_paid'],summary['outstanding_balance']),
                         (D('800'),D('800'),D('300'),D('500')))
        self.assertFalse(row.order.payments.exists())
        self.assertFalse(row.order.adjustments.exists())
        self.assertEqual(get_receipt_data(row.order)['reservation_credit_applied'],D('300'))
        self.assertEqual(get_financial_summary(prefetch_financials(TableOrder.objects.filter(pk=row.order.pk))[0]),summary)
        payments._assert_ledger(row.order)
        with self.assertRaises(ValidationError):
            orders.cancel_sent_line(line,self.admin,'Cambio')
        payment=payments.pay_full_balance(row.order,'CARD',self.admin,card_approved=True)
        self.assertEqual(payment.amount,D('500'))
        payments.close_order(row.order,self.admin)
        self.assertEqual(get_operational_table_state(self.table),'AVAILABLE')

    def test_fee_does_not_reduce_consumption(self):
        row=self.arrive(paid=True,application='FEE')
        self.consume(row)
        self.assertEqual(get_financial_summary(row.order)['outstanding_balance'],D('800'))
        self.assertFalse(row.order.reservation_credits.exists())

    def test_remaining_credit_applies_later_once(self):
        row=self.arrive(paid=True)
        line=self.consume(row,200)
        self.assertEqual(credit_summary(row.order)['remaining'],D('100'))
        orders.add_product_to_order(row.order,line.product,1,self.admin)
        orders.send_order(row.order,self.admin)
        orders.send_order(row.order,self.admin)
        self.assertEqual(get_financial_summary(row.order)['outstanding_balance'],D('100'))
        self.assertEqual(credit_summary(row.order)['applied'],D('300'))

    def test_credit_prevents_merge_and_split(self):
        row=self.arrive(paid=True)
        with self.assertRaises(ValidationError):
            orders.change_billing_mode(row.order,'SPLIT',self.admin)

    def test_pending_and_paid_are_table_state_priority(self):
        row=self.arrive(paid=True);self.consume(row)
        self.assertEqual(get_operational_table_state(self.table),'PARTIALLY_PAID')
        payments.pay_full_balance(row.order,'TRANSFER',self.admin,reference='R')
        self.assertEqual(get_operational_table_state(self.table),'PAYMENT_PENDING')

    def test_credit_detects_corruption_and_blocks_close(self):
        from apps.reservations.models import ReservationCredit
        row=self.arrive(paid=True);self.consume(row,300)
        ReservationCredit.objects.filter(order=row.order).update(amount=299)
        self.assertFalse(payments.can_close_order(row.order))
        with self.assertRaises(ValidationError):
            payments.close_order(row.order,self.admin)

    def test_refund_never_refunds_reservation_credit(self):
        row=self.arrive(paid=True);self.consume(row)
        payment=payments.pay_full_balance(row.order,'CARD',self.admin,card_approved=True)
        with self.assertRaises(ValidationError):
            payments.refund_payment(payment,self.admin,amount=800,reason='Cambio')
        payments.refund_payment(payment,self.admin,amount=500,reason='Cambio')
        summary=get_financial_summary(row.order)
        self.assertEqual(summary['confirmed_paid'],D('300'))
        self.assertEqual(summary['charge_total'],D('300'))
        self.assertEqual(summary['outstanding_balance'],D('0'))
        self.assertEqual(row.payment.status,'CONFIRMED')

    def test_unused_credit_remains_after_close(self):
        row=self.arrive(paid=True);self.consume(row,200)
        payments.close_order(row.order,self.admin)
        self.assertEqual(credit_summary(row.order)['remaining'],D('100'))
        self.assertEqual(row.payment.status,'CONFIRMED')

    def test_net_sales_and_cash_collections_keep_distinct_meanings(self):
        from apps.cash.queries import get_business_day_summary
        row=self.arrive(paid=True);self.consume(row)
        payments.pay_full_balance(row.order,'CARD',self.admin,card_approved=True)
        summary=get_business_day_summary(row.order.business_day)
        self.assertEqual(summary['net_sales'],D('800'))
        self.assertEqual(summary['payments_by_method']['CARD']['confirmed_net'],D('500'))
        self.assertEqual(summary['payments_by_method']['TRANSFER']['confirmed_net'],D('0'))

    def test_reserved_destination_cannot_receive_move_or_join(self):
        from apps.tables.models import VenueTable
        self.day();row=self.confirmed()
        other=VenueTable.objects.create(area=self.area,name='Otra mesa',capacity=4)
        order=orders.open_table_order(other,self.admin)
        with patch('apps.reservations.queries.timezone.now',return_value=row.starts_at+timedelta(minutes=1)):
            with self.assertRaises(ValidationError):
                orders.move_order_to_table(order,self.table,self.admin)
            with self.assertRaises(ValidationError):
                orders.join_table_to_order(order,self.table,self.admin)

    def test_map_includes_reserved_and_arrival_changes_it(self):
        from apps.operations.queries import get_operational_map
        self.day();row=self.confirmed()
        with patch('apps.reservations.queries.timezone.now',return_value=row.starts_at+timedelta(minutes=1)):
            data=get_operational_map(self.area)
            self.assertEqual(data['groups'][0]['tables'][0]['state_label'],'Reservada')
            s.confirm_reservation_arrival(row,self.manager,self.waiter)
            data=get_operational_map(self.area)
            self.assertEqual(data['groups'][0]['tables'][0]['state_label'],'Ocupada')


    def test_early_arrival_keeps_original_interval_until_order_closes(self):
        row=self.arrive()
        available=lambda:get_available_tables(row.reservation_date,row.start_time,row.duration_minutes).filter(pk=row.table_id).exists()
        self.assertFalse(available())
        payments.close_order(row.order,self.admin)
        self.assertTrue(available())
