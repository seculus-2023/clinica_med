"""Exportação para Excel (.xlsx) com cabeçalho formatado, números como número e moeda em R$."""
import io
import re
from datetime import date, datetime
from decimal import Decimal

from django.http import HttpResponse

MOEDA = re.compile(r'^-?R\$ ?-?[\d.]+,\d{2}$')


def _converter(v):
    """Transforma 'R$ 1.234,56' e '12,5%' em número para o Excel calcular."""
    if isinstance(v, (int, float, Decimal, date, datetime)) or v is None:
        return (float(v) if isinstance(v, Decimal) else v), ('moeda' if isinstance(v, Decimal) else None)
    s = str(v).strip()
    if MOEDA.match(s):
        n = s.replace('R$', '').replace(' ', '').replace('.', '').replace(',', '.')
        return float(n), 'moeda'
    if re.match(r'^-?\d+,\d+%$', s):
        return float(s[:-1].replace(',', '.')) / 100, 'pct'
    if re.match(r'^-?\d+$', s) and len(s) < 12:
        return int(s), None
    return s, None


def xlsx_bytes(nome_aba, cabecalho, linhas, titulo=''):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = re.sub(r'[\[\]:*?/\\]', '-', nome_aba)[:31] or 'Relatório'
    linha = 1
    if titulo:
        ws.cell(row=1, column=1, value=titulo).font = Font(bold=True, size=13)
        linha = 3
    cor = PatternFill('solid', fgColor='139E86')
    for i, c in enumerate(cabecalho, 1):
        cel = ws.cell(row=linha, column=i, value=str(c))
        cel.font, cel.fill, cel.alignment = Font(bold=True, color='FFFFFF'), cor, Alignment(vertical='center')
    larguras = [len(str(c)) + 2 for c in cabecalho]
    for r in linhas:
        linha += 1
        destaque = bool(r) and str(r[0]).isupper() and len(str(r[0])) > 2
        for i, v in enumerate(r, 1):
            valor, fmt = _converter(v)
            cel = ws.cell(row=linha, column=i, value=valor)
            if fmt == 'moeda':
                cel.number_format = 'R$ #,##0.00;[Red]-R$ #,##0.00'
            elif fmt == 'pct':
                cel.number_format = '0.0%'
            elif isinstance(valor, (date, datetime)):
                cel.number_format = 'dd/mm/yyyy'
            if destaque or (str(r[0]).lower().startswith(('total', 'resultado'))):
                cel.font = Font(bold=True)
            if i <= len(larguras):
                larguras[i - 1] = min(max(larguras[i - 1], len(str(v)) + 2), 60)
    for i, w in enumerate(larguras, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = ws.cell(row=(4 if titulo else 2), column=1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def xlsx_resposta(nome_aba, cabecalho, linhas, nome_arquivo, titulo=''):
    resp = HttpResponse(xlsx_bytes(nome_aba, cabecalho, linhas, titulo),
                        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = f'attachment; filename="{nome_arquivo}"'
    return resp
