from datetime import timedelta
from decimal import Decimal
from io import BytesIO
import json
from unittest.mock import patch
from django.core.exceptions import ValidationError, PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from pypdf import PdfReader
from apps.audit.models import AuditLog
from apps.events import services as s, queries as q
from apps.events.models import *
from apps.events.documents import tickets_pdf, ticket_qr, ticket_url
from .base import EventCase, picture


class DomainTests(EventCase):
    def test_created_draft_and_no_automatic_types(self):
        row=s.create_event(self.manager,name='Otro',starts_at=self.start,ends_at=self.start+timedelta(hours=3))
        self.assertEqual(row.status,'DRAFT');self.assertEqual(row.ticket_types.count(),0);self.assertIsNone(row.published_at)

    def test_dates_must_be_aware_and_increasing(self):
        for end in [self.start,self.start-timedelta(hours=1)]:
            with self.assertRaises(ValidationError):s.create_event(self.manager,name='Mal',starts_at=self.start,ends_at=end)
        with self.assertRaises(ValidationError):s.create_event(self.manager,name='Mal',starts_at=self.start.replace(tzinfo=None),ends_at=self.start+timedelta(hours=1))

    def test_publication_structured_errors(self):
        row=s.create_event(self.manager,name='Borrador',starts_at=self.start,ends_at=self.start+timedelta(hours=3))
        self.assertEqual({e['field'] for e in s.validate_event_for_publication(row)},{'image','maximum_capacity','ticket_types'})
        with self.assertRaises(ValidationError):s.publish_event(row,self.manager)

    def test_published_has_timestamp_and_audit(self):
        self.assertIsNotNone(self.event.published_at)
        self.assertTrue(AuditLog.objects.filter(action='events.published',entity_id=str(self.event.pk)).exists())

    def test_publishing_overallocation_including_courtesy_and_tables(self):
        row=s.duplicate_event(self.event,self.manager)
        s.edit_event(row,self.manager,maximum_capacity=95)
        with self.assertRaises(ValidationError):s.publish_event(row,self.manager)

    def test_duplicate_only_configuration(self):
        self.confirm();copy=s.duplicate_event(self.event,self.manager)
        self.assertEqual(copy.status,'DRAFT');self.assertIsNone(copy.published_at)
        self.assertEqual(copy.ticket_types.count(),3);self.assertEqual(copy.table_configurations.count(),1)
        self.assertEqual(copy.purchases.count(),0);self.assertEqual(copy.tickets.count(),0)
        self.assertNotEqual(copy.slug,self.event.slug)

    def test_safe_edit_and_published_dates_require_reschedule(self):
        s.edit_event(self.event,self.manager,name='Nuevo nombre')
        self.event.refresh_from_db();self.assertEqual(self.event.name,'Nuevo nombre')
        with self.assertRaises(ValidationError):s.edit_event(self.event,self.manager,starts_at=self.start+timedelta(days=1))

    def test_service_cannot_change_state_arbitrarily(self):
        with self.assertRaises(ValidationError):s.edit_event(self.event,self.manager,status='CONFIRMED')

    def test_negative_price_and_courtesy_nonzero_rejected(self):
        for value in [-1,'NaN','10.001']:
            with self.assertRaises(ValidationError):s.save_ticket_type(self.event,self.manager,self.general,price=value)
        with self.assertRaises(ValidationError):s.save_ticket_type(self.event,self.manager,self.courtesy,price=1)

    def test_future_and_ended_sales_are_unavailable(self):
        s.save_ticket_type(self.event,self.manager,self.general,sale_starts_at=self.start-timedelta(hours=1))
        with self.assertRaises(ValidationError):self.buy()
        s.save_ticket_type(self.event,self.manager,self.general,sale_starts_at=timezone.now()-timedelta(days=2),sale_ends_at=timezone.now()-timedelta(days=1))
        with self.assertRaises(ValidationError):self.buy()
        self.assertFalse(q.ticket_type_rows(self.event)[0].sellable)

    def test_inactive_and_courtesy_not_publicly_sellable(self):
        s.save_ticket_type(self.event,self.manager,self.general,is_active=False)
        with self.assertRaises(ValidationError):self.buy()
        with self.assertRaises(ValidationError):self.buy({self.courtesy.pk:1})

    def test_window_inclusive_at_boundary(self):
        now=self.general.sale_starts_at
        with patch('django.utils.timezone.now',return_value=now):
            self.assertEqual(self.buy().items.count(),1)

    def test_sale_windows_validate(self):
        with self.assertRaises(ValidationError):s.save_ticket_type(self.event,self.manager,self.general,sale_starts_at=self.start+timedelta(days=1))

    def test_mixed_purchase_snapshots_and_amount(self):
        row=self.buy({self.general.pk:2,self.vip.pk:1})
        self.assertEqual(row.amount,Decimal('350'))
        s.save_ticket_type(self.event,self.manager,self.general,price=120)
        row.refresh_from_db();self.assertEqual(row.amount,Decimal('350'))
        self.assertEqual(row.tickets.count(),0)

    def test_quantities_and_maximum_validated(self):
        for n in [0,-1,11,True,1.5]:
            with self.assertRaises(ValidationError):self.buy({self.general.pk:n})

    def test_wrong_event_type_rejected(self):
        other=s.duplicate_event(self.event,self.manager)
        with self.assertRaises(ValidationError):self.buy({other.ticket_types.first().pk:1})

    def test_no_empty_or_mixed_table_and_individual_purchase(self):
        with self.assertRaises(ValidationError):self.buy({})
        with self.assertRaises(ValidationError):s.create_purchase(self.event,'Ana','55555555',{self.general.pk:1},self.config)

    def test_customer_required(self):
        for name,phone in [('', '55555555'),('Ana','abc')]:
            with self.assertRaises(ValidationError):s.create_purchase(self.event,name,phone,{self.general.pk:1})

    def test_holds_reserve_quota_and_capacity(self):
        s.save_ticket_type(self.event,self.manager,self.general,capacity=2)
        row=self.buy()
        self.assertEqual(q.type_committed(self.general),2);self.assertEqual(q.get_event_capacity_summary(self.event)['held'],2)
        with self.assertRaises(ValidationError):self.buy()
        self.assertEqual(q.get_event_capacity_summary(self.event)['remaining'],98)

    def test_quota_and_global_reductions_below_commitments_rejected(self):
        self.buy()
        with self.assertRaises(ValidationError):s.save_ticket_type(self.event,self.manager,self.general,capacity=1)
        with self.assertRaises(ValidationError):s.edit_event(self.event,self.manager,maximum_capacity=1)

    def test_disabled_type_preserves_committed_pool(self):
        self.buy();s.save_ticket_type(self.event,self.manager,self.general,is_active=False)
        self.assertEqual(q.configuration_summary(self.event)['individual'],42)

    def test_table_snapshot_and_cover(self):
        self.table.capacity=8;self.table.save();self.config.refresh_from_db()
        self.assertEqual(self.config.capacity_snapshot,6);self.assertEqual(self.config.total_price,600)
        row=self.buy(table=True);self.assertEqual(row.amount,600);self.assertEqual(row.items.count(),0)
        self.assertFalse(q.table_available(self.config))

    def test_table_hold_prevents_second_purchase_and_reconfiguration(self):
        self.buy(table=True)
        with self.assertRaises(ValidationError):self.buy(table=True)
        with self.assertRaises(ValidationError):s.save_event_table(self.event,self.manager,self.table,self.vip,90)

    def test_table_generates_exact_accesses_without_individual_quota(self):
        tickets=self.confirm(self.buy(table=True))
        self.assertEqual(len(tickets),6);self.assertTrue(all(t.table_reservation_id for t in tickets))
        self.assertEqual(q.type_committed(self.vip),0)
        summary=q.get_event_capacity_summary(self.event)
        self.assertEqual((summary['table_accesses'],summary['held'],summary['remaining']),(6,0,94))

    def test_table_disabled_not_available(self):
        s.save_event_table(self.event,self.manager,self.table,self.vip,100,enabled=False)
        with self.assertRaises(ValidationError):self.buy(table=True)

    def test_settings_configure_both_deadlines(self):
        s.configure_settings(self.manager,purchase_hold_minutes=20,payment_window_minutes=5)
        now=timezone.now()
        with patch('django.utils.timezone.now',return_value=now):row=self.buy()
        self.assertEqual(row.hold_expires_at,now+timedelta(minutes=20));self.assertEqual(row.deadline,now+timedelta(minutes=5))

    def test_expiration_releases_types_and_table_idempotently(self):
        first=self.buy();second=self.buy(table=True)
        later=timezone.now()+timedelta(minutes=16)
        self.assertEqual(s.expire_event_purchases(later),2);self.assertEqual(s.expire_event_purchases(later),0)
        first.refresh_from_db();second.refresh_from_db()
        self.assertEqual(first.status,'EXPIRED');self.assertEqual(second.table_reservation.status,'EXPIRED')
        self.assertTrue(q.table_available(self.config));self.assertEqual(q.get_event_capacity_summary(self.event)['held'],0)

    def test_expired_pending_ignored_without_command(self):
        row=self.buy(table=True)
        EventPurchase.objects.filter(pk=row.pk).update(hold_expires_at=timezone.now()-timedelta(seconds=1))
        self.assertTrue(q.table_available(self.config));self.assertEqual(q.get_event_capacity_summary(self.event)['held'],0)
        with self.assertRaises(ValidationError):self.submit(row)

    def test_review_freezes_expiration(self):
        payment=self.submit()
        self.assertEqual(s.expire_event_purchases(timezone.now()+timedelta(days=1)),0)
        self.assertEqual(q.get_event_capacity_summary(self.event)['held'],2)
        self.assertEqual(payment.purchase.tickets.count(),0)

    def test_payment_reference_amount_and_proof_required(self):
        row=self.buy()
        for amount,reference,proof in [(199,'REF',picture()),(200,' ',picture()),(200,'REF',None)]:
            with self.assertRaises(ValidationError):s.submit_event_payment(row,amount,reference,proof)

    def test_real_image_validation(self):
        for upload in [SimpleUploadedFile('x.png',b'<script>evil</script>',content_type='image/png'),SimpleUploadedFile('large.png',b'x'*(5*1024*1024+1))]:
            with self.assertRaises(ValidationError):s.validate_image(upload)
        upload=picture('unsafe.html')
        s.validate_image(upload)
        self.assertEqual(upload.name,'image.png')

    def test_proofs_are_private(self):
        payment=self.submit()
        self.assertIn(self.storage.name,payment.proof_image.path)
        with self.assertRaises(ValueError):_ = payment.proof_image.url

    def test_confirmation_exact_idempotent_unique(self):
        payment=self.submit(self.buy({self.general.pk:2,self.vip.pk:1}))
        first=s.confirm_event_payment(payment,self.manager);second=s.confirm_event_payment(payment,self.manager)
        third=s.generate_purchase_tickets(payment.purchase,self.manager)
        self.assertEqual([t.pk for t in first],[t.pk for t in second]);self.assertEqual(len(third),3)
        self.assertEqual(len({t.qr_token for t in first}),3);self.assertEqual(len({t.ticket_number for t in first}),3)

    def test_no_ticket_generation_before_confirmation(self):
        row=self.buy()
        with self.assertRaises(ValidationError):s.generate_purchase_tickets(row,self.manager)
        self.assertEqual(row.tickets.count(),0)

    def test_rejection_requires_reason_and_releases_capacity(self):
        payment=self.submit(self.buy(table=True))
        with self.assertRaises(ValidationError):s.reject_event_payment(payment,self.manager,' ')
        s.reject_event_payment(payment,self.manager,'No recibido')
        payment.refresh_from_db();self.assertEqual(payment.status,'REJECTED');self.assertEqual(payment.purchase.status,'REJECTED')
        self.assertTrue(q.table_available(self.config));self.assertEqual(EventTicket.objects.count(),0)

    def test_courtesy_counts_quota_and_no_revenue(self):
        tickets=s.issue_courtesy_tickets(self.event,self.courtesy,2,self.manager,'Invitados')
        self.assertEqual(q.get_event_capacity_summary(self.event)['courtesy'],2)
        self.assertTrue(all(t.purchase_id is None for t in tickets));self.assertEqual(q.type_committed(self.courtesy),2)
        with self.assertRaises(ValidationError):s.issue_courtesy_tickets(self.event,self.courtesy,9,self.manager)

    def test_courtesy_needs_courtesy_type(self):
        with self.assertRaises(ValidationError):s.issue_courtesy_tickets(self.event,self.vip,1,self.manager)

    def test_summary_all_pools_and_present(self):
        individual=self.confirm();self.confirm(self.buy(table=True));s.issue_courtesy_tickets(self.event,self.courtesy,2,self.manager)
        self.buy({self.vip.pk:3});s.validate_and_use_ticket(individual[0].qr_token,self.guard)
        self.assertEqual(q.get_event_capacity_summary(self.event),dict(maximum_capacity=100,held=3,sold_individual=2,courtesy=2,table_accesses=6,used_at_entrance=1,remaining=87))

    def test_use_once_and_preserve_original_time(self):
        ticket=self.confirm()[0]
        first=s.validate_and_use_ticket(ticket.qr_token,self.guard);second=s.validate_and_use_ticket(ticket.qr_token,self.guard)
        self.assertEqual(first['result'],'VALID');self.assertEqual(second['result'],'USED');self.assertEqual(first['used_at'],second['used_at'])
        ticket.refresh_from_db();self.assertEqual(ticket.used_by,self.guard)
        self.assertNotIn('customer_name',first)

    def test_invalid_and_courtesy_scan(self):
        for value in ['missing',self.buy().secure_token,None]:self.assertEqual(s.validate_and_use_ticket(value,self.guard)['result'],'INVALID')
        ticket=s.issue_courtesy_tickets(self.event,self.courtesy,1,self.manager)[0]
        self.assertEqual(s.validate_and_use_ticket(ticket.qr_token,self.guard)['result'],'VALID')

    def test_scan_requires_guard_role_and_permission(self):
        ticket=self.confirm()[0]
        with self.assertRaises(PermissionDenied):s.validate_and_use_ticket(ticket.qr_token,self.manager)
        self.guard.user_permissions.clear();self.guard.__dict__.pop('_perm_cache',None);self.guard.__dict__.pop('_user_perm_cache',None)
        with self.assertRaises(PermissionDenied):s.validate_and_use_ticket(ticket.qr_token,self.guard)

    def test_reschedule_keeps_qr_history_and_sales(self):
        ticket=self.confirm()[0];old=ticket.qr_token
        row=s.reschedule_event(self.event,self.manager,self.start+timedelta(days=1),self.start+timedelta(days=1,hours=6),'Cambio de fecha')
        ticket.refresh_from_db();self.assertEqual(ticket.qr_token,old);self.assertEqual(row.status,'RESCHEDULED')
        self.assertEqual(row.schedule_history.count(),1);self.assertEqual(s.validate_and_use_ticket(old,self.guard)['result'],'VALID')
        self.assertIsNotNone(self.buy())

    def test_cancel_invalidates_used_and_valid_preserves_payments(self):
        tickets=self.confirm();s.validate_and_use_ticket(tickets[0].qr_token,self.guard)
        s.cancel_event(self.event,self.manager,'Evento suspendido')
        self.assertFalse(self.event.tickets.exclude(status='CANCELLED').exists())
        tickets[0].refresh_from_db();self.assertIsNotNone(tickets[0].used_at)
        self.assertEqual(EventPurchasePayment.objects.get().status,'CONFIRMED')
        self.assertEqual(s.validate_and_use_ticket(tickets[1].qr_token,self.guard)['result'],'CANCELLED')
        with self.assertRaises(ValidationError):self.buy()

    def test_cancel_reason_and_idempotence(self):
        with self.assertRaises(ValidationError):s.cancel_event(self.event,self.manager,'')
        s.cancel_event(self.event,self.manager,'Cancelado');s.cancel_event(self.event,self.manager,'Reintento')
        self.assertEqual(AuditLog.objects.filter(action='events.cancelled').count(),1)

    def test_finish_blocks_scanning_and_sales(self):
        ticket=self.confirm()[0];s.finish_event(self.event,self.manager)
        self.assertEqual(s.validate_and_use_ticket(ticket.qr_token,self.guard)['result'],'INVALID')
        with self.assertRaises(ValidationError):self.buy()

    def test_finish_waits_for_reviews(self):
        self.submit()
        with self.assertRaises(ValidationError):s.finish_event(self.event,self.manager)

    def test_minimal_snapshot_hash_checksum_changes_on_scan(self):
        ticket=self.confirm()[0];before=q.build_event_access_snapshot(self.event)
        text=json.dumps(before)
        for private in ['Ana Compradora','55555555','amount',ticket.qr_token]:self.assertNotIn(private,text)
        self.assertEqual(before['version'],q.build_event_access_snapshot(self.event)['version'])
        s.validate_and_use_ticket(ticket.qr_token,self.guard)
        self.assertNotEqual(before['version'],q.build_event_access_snapshot(self.event)['version'])

    def test_pdf_single_combined_qr_and_reproducibility(self):
        tickets=self.confirm(self.buy({self.general.pk:2,self.vip.pk:1}))
        single=tickets_pdf(tickets[:1]);combined=tickets_pdf(tickets)
        self.assertEqual(len(PdfReader(single).pages),1);reader=PdfReader(combined);self.assertEqual(len(reader.pages),3)
        for page,ticket in zip(reader.pages,tickets):
            self.assertIn(ticket.ticket_number,page.extract_text());self.assertIn('Ana Compradora',page.extract_text());self.assertTrue(page.images)
        self.assertEqual(tickets_pdf(tickets).getvalue(),combined.getvalue())
        self.assertTrue(ticket_qr(tickets[0]).getvalue().startswith(b'\x89PNG'))
        self.assertNotIn(tickets[0].purchase.secure_token,ticket_url(tickets[0]))

    def test_permissions_explicit_not_role_based(self):
        self.revoke('publish_event');copy=s.duplicate_event(self.event,self.manager)
        with self.assertRaises(PermissionDenied):s.publish_event(copy,self.manager)
        self.revoke('verify_event_payment')
        with self.assertRaises(PermissionDenied):s.confirm_event_payment(self.submit(),self.manager)

    def test_no_physical_delete_service_model(self):
        with self.assertRaises(ValidationError):self.event.delete()
        with self.assertRaises(ValidationError):self.general.delete()
