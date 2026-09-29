"""PDF transitorio, autenticado y con un límite explícito de filas."""
from io import BytesIO
from xml.sax.saxutils import escape
from django.core.exceptions import ValidationError
from django.utils import timezone
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from apps.core.configuration import business


def generate(report, period, user):
    if sum(len(section['rows']) for section in report['sections']) > 1000:
        raise ValidationError('El PDF admite hasta 1,000 filas. Reduce el periodo para exportarlo.')
    buffer = BytesIO()
    size = landscape(A4)
    doc = SimpleDocTemplate(buffer, pagesize=size, rightMargin=32, leftMargin=32, topMargin=30, bottomMargin=35,
                           title=report['title'], author=user.get_full_name() or user.username)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name='Cell', fontName='Helvetica', fontSize=8, leading=11, textColor=colors.HexColor('#222222'), wordWrap='CJK'))
    styles.add(ParagraphStyle(name='SmallInfo', fontSize=9, leading=13, textColor=colors.HexColor('#555555')))
    def p(value, style='Cell'):
        return Paragraph(escape(str(value)), styles[style])
    generated = timezone.localtime().strftime('%d/%m/%Y %H:%M')
    story = [p(business().business_name, 'Title'), p(report['title'], 'Heading1'),
             p('Periodo: '+period.label, 'SmallInfo'), p(f'Generado: {generated} · Por: {user.get_full_name() or user.username}', 'SmallInfo'), Spacer(1,12)]
    def table(columns, rows):
        n = len(columns)
        cells = [[p(v) for v in columns]] + [[p(v) for v in row] for row in rows]
        result = Table(cells, colWidths=[(size[0]-64)/n]*n, repeatRows=1, splitInRow=1, hAlign='LEFT')
        result.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#e8dfce')),
            ('VALIGN',(0,0),(-1,-1),'TOP'), ('LEFTPADDING',(0,0),(-1,-1),6), ('RIGHTPADDING',(0,0),(-1,-1),6),
            ('TOPPADDING',(0,0),(-1,-1),6), ('BOTTOMPADDING',(0,0),(-1,-1),6),
            ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#b5a383')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#f7f7f5')])]))
        return result
    if report['kpis']:
        story += [table(['Concepto','Total'], report['kpis']), Spacer(1,14)]
    for section in report['sections']:
        if not section['rows']: continue
        story.extend([p(section['title'], 'Heading2'), table(section['columns'], section['rows']), Spacer(1,14)])
    story.append(p('Ventas por jornada comercial. Bruto menos ajustes y reembolsos = consumo neto. Cobros y anticipos se presentan por separado. Reservas y eventos: fecha programada local. Documento generado con datos actuales; no sustituye un cierre.', 'SmallInfo'))
    def footer(canvas, document):
        canvas.saveState(); canvas.setFont('Helvetica', 8); canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawString(32, 19, 'BIG PARTY · Reporte de Gerencia · America/Guatemala')
        canvas.drawRightString(size[0]-32, 19, f'Página {document.page}')
        canvas.restoreState()
    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()
