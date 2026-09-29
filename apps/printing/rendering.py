"""Snapshots y texto independientes del transporte; nunca interpretar notas como comandos."""
import json
import textwrap
import unicodedata
from django.core.serializers.json import DjangoJSONEncoder
from django.utils import timezone
from apps.payments.queries import get_receipt_data


def clean(value):
    return ''.join(c for c in str(value) if c in '\n\t' or not unicodedata.category(c).startswith('C')).replace('\t', ' ')


def serializable(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def render(lines, width='80'):
    columns = 32 if width == '58' else 48
    output = []
    for value in lines:
        if value == '--':
            output.append('-' * columns)
        else:
            for line in clean(value).split('\n'):
                output.extend(textwrap.wrap(line, width=columns, replace_whitespace=False, drop_whitespace=True) or [''])
    return '\n'.join(output) + '\n'


def ticket_snapshot(ticket, items, printer, destination):
    order = ticket.order
    actor = ticket.created_by.get_full_name().strip() or ticket.created_by.username
    lines = ['BIG PARTY', destination.upper(), '']
    marker = {'ADDITION': 'ADICIÓN', 'CANCELLATION': 'CANCELACIÓN', 'UPDATE': 'ACTUALIZACIÓN'}.get(ticket.ticket_type)
    if marker:
        lines += [f'*** {marker} ***', '']
    if ticket.table_name_snapshot:
        lines.append(ticket.table_name_snapshot.upper())
    lines.append(f'PEDIDO {ticket.order_number_snapshot or order.order_number}')
    if order.order_type == 'QUICK_SALE':
        lines.append(ticket.cash_register_snapshot or order.cash_session.register.name)
        if ticket.customer_alias_snapshot:
            lines += ['ALIAS:', ticket.customer_alias_snapshot]
    stamp = timezone.localtime(ticket.created_at).strftime('%d/%m/%Y %H:%M:%S')
    lines += [stamp, '--']
    if ticket.ticket_type == 'CANCELLATION':
        lines.append('CANCELAR:')
    item_data = []
    for item in items:
        lines += [f'{item.quantity}  {item.description_snapshot.upper()}']
        if item.notes_snapshot:
            lines += ['NUEVA NOTA:' if ticket.ticket_type == 'UPDATE' else 'NOTA:', item.notes_snapshot, '']
        item_data.append({'id': item.pk, 'quantity': item.quantity, 'description': item.description_snapshot, 'notes': item.notes_snapshot, 'route': item.route, 'area_id': item.area_id})
    lines += ['--', f'{"CAJA" if order.order_type == "QUICK_SALE" else "MESERO"}: {actor.upper()}']
    width = printer.paper_width if printer else '80'
    return {'version': 1, 'kind': ticket.ticket_type, 'destination': destination, 'order_number': order.order_number, 'timestamp': stamp,
            'table': ticket.table_name_snapshot, 'alias': ticket.customer_alias_snapshot, 'actor': actor, 'items': item_data,
            'paper_width': width, 'text': render(lines, width)}


def receipt_snapshot(order, printer):
    data = get_receipt_data(order)
    lines = ['BIG PARTY', 'RECIBO', timezone.localtime().strftime('%d/%m/%Y %H:%M:%S'), f'PEDIDO {order.order_number}']
    if order.primary_table_id:
        lines.append(order.primary_table.name.upper())
    lines += ['--']
    for row in data['lines']:
        lines += [row['description'], f"{row['quantity']} x Q{row['unit_price']:.2f}  Q{row['subtotal']:.2f}"]
        lines += row['modifiers']
    lines += ['--', f"SUBTOTAL Q{data['gross_total']:.2f}"]
    for adjustment in data['adjustments']:
        lines.append(f"{'CORTESÍA' if adjustment['type'] == 'COURTESY' else 'DESCUENTO'} -Q{adjustment['amount']:.2f}")
    if data['refund_total']:
        lines.append(f"REEMBOLSOS Q{data['refund_total']:.2f}")
    lines += [f"TOTAL Q{data['charge_total']:.2f}", '--']
    methods = {'CASH':'Efectivo', 'CARD':'Tarjeta', 'TRANSFER':'Transferencia', 'DEPOSIT':'Depósito'}
    for payment in data['payments']:
        if payment['status'] in ('CONFIRMED', 'REFUNDED'):
            lines.append(f"{methods[payment['method']]} Q{payment['amount']:.2f}")
    lines += [f"SALDO Q{data['outstanding_balance']:.2f}", '', 'Gracias por tu visita']
    width = printer.paper_width if printer else '80'
    return {'version': 1, 'kind': 'RECEIPT', 'destination': printer.name if printer else 'Barra del área', 'paper_width': width,
            'data': serializable(data), 'text': render(lines, width)}


def test_snapshot(printer):
    lines = ['BIG PARTY', 'PRUEBA DE IMPRESIÓN', printer.name, timezone.localtime().strftime('%d/%m/%Y %H:%M:%S'), '--',
             'ABCDEFGHIJKLMNOPQRSTUVWXYZ', '0123456789', 'á é í ó ú ñ', 'Cóctel · Adición · Cancelación', '--']
    return {'version':1, 'kind':'TEST', 'destination':printer.name, 'paper_width':printer.paper_width, 'text':render(lines, printer.paper_width)}


def copy_snapshot(original, reason):
    data = dict(original.payload_snapshot)
    data['text'] = render(['*** REIMPRESIÓN ***', f'Original #{original.pk}', f'Motivo: {reason}', '--'], data['paper_width']) + data['text']
    return data
