"""PDF de una entrada por página; QR y portal usan secretos independientes."""
from io import BytesIO
from xml.sax.saxutils import escape
import qrcode
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle


def ticket_url(ticket):
    return settings.PUBLIC_BASE_URL + reverse('event-access:ticket', args=[ticket.qr_token])


def ticket_qr(ticket):
    image = qrcode.make(ticket_url(ticket), error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=8)
    output = BytesIO()
    image.save(output, format='PNG')
    output.seek(0)
    return output


def tickets_pdf(tickets):
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=(420, 680), invariant=1)
    pdf.setTitle('BIG PARTY · Entradas')
    pdf.setAuthor('BIG PARTY')
    def text(value, y, size=12, color='#eeeeea', bold=False, max_height=100):
        style = ParagraphStyle('ticket', fontName='Helvetica-Bold' if bold else 'Helvetica', fontSize=size,
            leading=size*1.25, textColor=HexColor(color))
        p = Paragraph(escape(str(value)), style)
        _, height = p.wrap(348, 100)
        while height > max_height and style.fontSize > 8:
            style.fontSize -= 1
            style.leading = style.fontSize * 1.25
            p = Paragraph(escape(str(value)), style)
            _, height = p.wrap(348, 100)
        p.drawOn(pdf, 36, y-height)
    for ticket in tickets:
        pdf.setFillColor(HexColor('#171818'))
        pdf.rect(0, 0, 420, 680, fill=1, stroke=0)
        text('BIG PARTY', 638, 23, '#d5bd95', True)
        text('ENTRADA INDIVIDUAL', 603, 9, '#b9b7b0')
        text(ticket.event.name, 568, 22, bold=True, max_height=62)
        start, end = timezone.localtime(ticket.event.starts_at), timezone.localtime(ticket.event.ends_at)
        text(start.strftime('%d/%m/%Y · %H:%M') + ' - ' + end.strftime('%d/%m/%Y · %H:%M'), 498, 10)
        text(ticket.ticket_type.name, 470, 15, '#d5bd95', True, max_height=27)
        pdf.drawImage(ImageReader(ticket_qr(ticket)), 100, 222, 220, 220, mask='auto')
        text(ticket.ticket_number, 200, 13, bold=True)
        text(ticket.get_status_display() + (' · Evento cancelado' if ticket.event.status == 'CANCELLED' else ''), 175, 11, '#d5bd95')
        buyer = ticket.purchase.customer_name if ticket.purchase_id else 'Cortesía'
        text('Comprador: ' + buyer, 142, 10)
        text('Presenta este QR en el acceso. Válido para una persona y un solo ingreso. No compartas el portal de tu compra.', 92, 9, '#b9b7b0')
        pdf.showPage()
    pdf.save()
    output.seek(0)
    return output
