from django.dispatch import receiver
from apps.orders.signals import preparation_ticket_created
from .services import create_print_jobs_for_ticket


@receiver(preparation_ticket_created, dispatch_uid='printing.ticket.outbox')
def ticket_ready(sender, ticket, **kwargs):
    create_print_jobs_for_ticket(ticket)
