from django.dispatch import Signal

# Evento de dominio emitido cuando la comanda y todos sus detalles ya existen.
preparation_ticket_created = Signal()
