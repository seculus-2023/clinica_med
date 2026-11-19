"""Importação de tabelas oficiais.

* CMED / ANVISA (Preços Máximos de Medicamentos) - planilha publicada pela ANVISA
  (https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos), em .xlsx, .xls ou .csv.
  O cabeçalho é localizado automaticamente (a planilha traz notas antes da tabela).
* SUS - SIGTAP (Tabela Unificada de Procedimentos) - arquivo ZIP da competência baixado em
  http://sigtap.datasus.gov.br (Tabela Unificada > Download), ou o tb_procedimento.txt extraído.
* CSV genérico de procedimentos (TUSS/CBHPM/própria): colunas codigo;nome;valor
"""
import csv
import io
import re
import unicodedata
import zipfile
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone

from .models import Medicamento, Procedimento

LOTE = 1000


class ErroImportacao(Exception):
    pass


def norm(txt):
    txt = unicodedata.normalize('NFKD', str(txt or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', txt).strip().upper()


def decimal_br(v):
    if v in (None, ''):
        return None
    if isinstance(v, (int, float, Decimal)):
        return Decimal(str(v)).quantize(Decimal('0.01'))
    s = str(v).strip().replace('R$', '').strip()
    if not s or s in ('-', '*'):
        return None
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return Decimal(s).quantize(Decimal('0.01'))
    except InvalidOperation:
        return None


def _texto(v, n=None):
    if v is None:
        return ''
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    return s[:n] if n else s


# ------------------------------------------------------------------ leitura de planilhas
def ler_linhas(arquivo):
    """Retorna um iterador de listas (linhas) a partir de xlsx/xls/csv."""
    nome = arquivo.name.lower()
    dados = arquivo.read()
    if nome.endswith('.xlsx'):
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(dados), read_only=True, data_only=True)
        ws = wb.worksheets[0]
        for row in ws.iter_rows(values_only=True):
            yield list(row)
        wb.close()
    elif nome.endswith('.xls'):
        import xlrd
        sh = xlrd.open_workbook(file_contents=dados).sheet_by_index(0)
        for i in range(sh.nrows):
            yield sh.row_values(i)
    elif nome.endswith(('.csv', '.txt')):
        for enc in ('utf-8-sig', 'cp1252', 'latin-1'):
            try:
                texto = dados.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        amostra = texto[:5000]
        contagem = {d: amostra.count(d) for d in (';', ',', '\t')}
        delim = max(contagem, key=contagem.get)
        yield from csv.reader(io.StringIO(texto), delimiter=delim)
    else:
        raise ErroImportacao('Formato não suportado. Envie .xlsx, .xls ou .csv.')


# ------------------------------------------------------------------ CMED
def _mapa_cabecalho(cab):
    return {norm(c).replace(' ', ''): i for i, c in enumerate(cab) if c not in (None, '')}


def _col(mapa, *nomes, prefixo=False):
    for n in nomes:
        n = n.replace(' ', '')
        if n in mapa:
            return mapa[n]
        if prefixo:
            for k, i in mapa.items():
                if k.startswith(n):
                    return i
    return None


def importar_cmed(clinica, arquivo, aliquota='18', somente_comercializados=True, atualizar_existentes=True):
    linhas = ler_linhas(arquivo)
    mapa = None
    for row in linhas:
        txt = {norm(c) for c in row if c not in (None, '')}
        if 'PRODUTO' in txt and 'LABORATORIO' in txt and any(t.startswith('APRESENTA') for t in txt):
            mapa = _mapa_cabecalho(row)
            break
    if not mapa:
        raise ErroImportacao('Cabeçalho da tabela CMED não encontrado (colunas PRODUTO, LABORATÓRIO, '
                             'APRESENTAÇÃO). Verifique se é a planilha de preços da ANVISA.')

    aliq = str(aliquota).replace('.', ',').replace('%', '').strip().upper()
    if aliq in ('SEM IMPOSTOS', 'SEMIMPOSTOS'):
        c_pf, c_pmc = _col(mapa, 'PF SEM IMPOSTOS'), None
    else:
        c_pf = _col(mapa, f'PF {aliq}%', f'PF {aliq} %')
        c_pmc = _col(mapa, f'PMC {aliq}%', f'PMC {aliq} %')
    if c_pf is None:
        disponiveis = sorted(k for k in mapa if k.startswith('PF'))
        raise ErroImportacao(f'Coluna de preço "PF {aliq}%" não encontrada. Disponíveis: {", ".join(disponiveis)}')

    c = {
        'substancia': _col(mapa, 'SUBSTANCIA'), 'cnpj': _col(mapa, 'CNPJ'),
        'lab': _col(mapa, 'LABORATORIO'), 'ggrem': _col(mapa, 'CODIGO GGREM'),
        'registro': _col(mapa, 'REGISTRO'), 'ean': _col(mapa, 'EAN 1', 'EAN'),
        'produto': _col(mapa, 'PRODUTO'), 'apres': _col(mapa, 'APRESENTACAO'),
        'classe': _col(mapa, 'CLASSE TERAPEUTICA'),
        'tipo': _col(mapa, 'TIPO DE PRODUTO (STATUS DO PRODUTO)', 'TIPO DE PRODUTO', prefixo=True),
        'regime': _col(mapa, 'REGIME DE PRECO'), 'restricao': _col(mapa, 'RESTRICAO HOSPITALAR'),
        'tarja': _col(mapa, 'TARJA'), 'comerc': _col(mapa, 'COMERCIALIZACAO', prefixo=True),
    }

    def v(row, chave, n=None):
        i = c[chave]
        return _texto(row[i], n) if i is not None and i < len(row) else ''

    existentes = {}
    for m in Medicamento.objects.filter(clinica=clinica, origem='cmed'):
        existentes[m.codigo_ggrem or m.ean or f'{m.registro_anvisa}|{m.apresentacao}'] = m
    hoje = timezone.localdate()
    novos, alterados, ignorados, vistos = [], [], 0, set()
    campos_update = ['nome', 'principio_ativo', 'apresentacao', 'laboratorio', 'cnpj_laboratorio',
                     'registro_anvisa', 'codigo_ggrem', 'ean', 'classe_terapeutica', 'tipo_produto', 'tarja',
                     'regime_preco', 'preco_fabrica', 'preco_maximo_consumidor', 'aliquota_icms',
                     'restricao_hospitalar', 'controlado', 'atualizado_tabela_em', 'ativo']

    for row in linhas:
        if not row or c['produto'] is None or c['produto'] >= len(row) or not row[c['produto']]:
            continue
        if somente_comercializados and c['comerc'] is not None and norm(v(row, 'comerc')) in ('NAO', 'N'):
            ignorados += 1
            continue
        tarja = v(row, 'tarja', 60)
        dados = {
            'nome': v(row, 'produto', 200), 'principio_ativo': v(row, 'substancia', 500),
            'apresentacao': v(row, 'apres', 300), 'laboratorio': v(row, 'lab', 200),
            'cnpj_laboratorio': v(row, 'cnpj', 20), 'registro_anvisa': v(row, 'registro', 20),
            'codigo_ggrem': v(row, 'ggrem', 20), 'ean': v(row, 'ean', 20).replace('-', ''),
            'classe_terapeutica': v(row, 'classe', 200), 'tipo_produto': v(row, 'tipo', 60),
            'regime_preco': v(row, 'regime', 30), 'tarja': tarja,
            'preco_fabrica': decimal_br(row[c_pf]) if c_pf < len(row) else None,
            'preco_maximo_consumidor': decimal_br(row[c_pmc]) if c_pmc is not None and c_pmc < len(row) else None,
            'aliquota_icms': ('Sem impostos' if c_pmc is None else f'{aliq}%'),
            'restricao_hospitalar': norm(v(row, 'restricao')) in ('SIM', 'S'),
            'controlado': any(t in norm(tarja) for t in ('PRETA', 'RESTRI')),
            'atualizado_tabela_em': hoje, 'ativo': True,
        }
        if dados['ean'] in ('0', '-'):
            dados['ean'] = ''
        chave = dados['codigo_ggrem'] or dados['ean'] or f"{dados['registro_anvisa']}|{dados['apresentacao']}"
        if chave in vistos:
            continue
        vistos.add(chave)
        obj = existentes.get(chave)
        if obj:
            if atualizar_existentes:
                for k, val in dados.items():
                    setattr(obj, k, val)
                alterados.append(obj)
        else:
            novos.append(Medicamento(clinica=clinica, origem='cmed', via='', **dados))

    with transaction.atomic():
        Medicamento.objects.bulk_create(novos, batch_size=LOTE)
        if alterados:
            Medicamento.objects.bulk_update(alterados, campos_update, batch_size=LOTE)
    return {'novos': len(novos), 'atualizados': len(alterados), 'ignorados': ignorados}


# ------------------------------------------------------------------ SIGTAP
LAYOUT_SIGTAP_PADRAO = [  # coluna, início (1-based), fim
    ('CO_PROCEDIMENTO', 1, 10), ('NO_PROCEDIMENTO', 11, 260), ('TP_COMPLEXIDADE', 261, 261),
    ('TP_SEXO', 262, 262), ('QT_MAXIMA_EXECUCAO', 263, 266), ('QT_DIAS_PERMANENCIA', 267, 270),
    ('QT_PONTOS', 271, 274), ('VL_IDADE_MINIMA', 275, 278), ('VL_IDADE_MAXIMA', 279, 282),
    ('VL_SH', 283, 294), ('VL_SA', 295, 306), ('VL_SP', 307, 318), ('CO_FINANCIAMENTO', 319, 320),
    ('CO_RUBRICA', 321, 326), ('QT_TEMPO_PERMANENCIA', 327, 330), ('DT_COMPETENCIA', 331, 336),
]


def _layout_sigtap(texto):
    layout = []
    for row in csv.reader(io.StringIO(texto)):
        if len(row) >= 4 and row[2].strip().isdigit():
            layout.append((row[0].strip().upper(), int(row[2]), int(row[3])))
    return layout or LAYOUT_SIGTAP_PADRAO


def _centavos(s):
    s = (s or '').strip()
    return (Decimal(int(s)) / 100).quantize(Decimal('0.01')) if s.isdigit() else Decimal('0')


def _inteiro(s):
    s = (s or '').strip()
    return int(s) if s.isdigit() else None


def importar_sigtap(clinica, arquivo, atualizar_existentes=True):
    nome = arquivo.name.lower()
    dados = arquivo.read()
    layout_txt = None
    if nome.endswith('.zip'):
        try:
            z = zipfile.ZipFile(io.BytesIO(dados))
        except zipfile.BadZipFile as e:
            raise ErroImportacao('Arquivo ZIP inválido.') from e
        nomes = {n.lower().split('/')[-1]: n for n in z.namelist()}
        if 'tb_procedimento.txt' not in nomes:
            raise ErroImportacao('O ZIP não contém tb_procedimento.txt. Use o arquivo "Tabela Unificada" do SIGTAP.')
        conteudo = z.read(nomes['tb_procedimento.txt']).decode('latin-1')
        if 'tb_procedimento_layout.txt' in nomes:
            layout_txt = z.read(nomes['tb_procedimento_layout.txt']).decode('latin-1')
    elif nome.endswith('.txt'):
        conteudo = dados.decode('latin-1')
    else:
        raise ErroImportacao('Envie o ZIP da Tabela Unificada do SIGTAP ou o arquivo tb_procedimento.txt.')
    layout = _layout_sigtap(layout_txt) if layout_txt else LAYOUT_SIGTAP_PADRAO
    pos = {col: (ini - 1, fim) for col, ini, fim in layout}

    def campo(linha, col):
        if col not in pos:
            return ''
        a, b = pos[col]
        return linha[a:b].strip()

    existentes = {p.codigo: p for p in Procedimento.objects.filter(clinica=clinica, origem='sus')}
    novos, alterados, vistos = [], [], set()
    for linha in conteudo.splitlines():
        cod = campo(linha, 'CO_PROCEDIMENTO')
        if not cod.isdigit() or cod in vistos:
            continue
        vistos.add(cod)
        comp = campo(linha, 'DT_COMPETENCIA')
        d = {
            'nome': campo(linha, 'NO_PROCEDIMENTO')[:300], 'complexidade': campo(linha, 'TP_COMPLEXIDADE')[:1],
            'sexo': campo(linha, 'TP_SEXO')[:1], 'idade_minima': _inteiro(campo(linha, 'VL_IDADE_MINIMA')),
            'idade_maxima': _inteiro(campo(linha, 'VL_IDADE_MAXIMA')), 'valor_sh': _centavos(campo(linha, 'VL_SH')),
            'valor_sa': _centavos(campo(linha, 'VL_SA')), 'valor_sp': _centavos(campo(linha, 'VL_SP')),
            'competencia': f'{comp[:4]}/{comp[4:]}' if len(comp) == 6 else comp, 'ativo': True,
        }
        obj = existentes.get(cod)
        if obj:
            if atualizar_existentes:
                for k, val in d.items():
                    setattr(obj, k, val)
                alterados.append(obj)
        else:
            novos.append(Procedimento(clinica=clinica, origem='sus', codigo=cod, **d))
    if not vistos:
        raise ErroImportacao('Nenhum procedimento encontrado no arquivo.')
    with transaction.atomic():
        Procedimento.objects.bulk_create(novos, batch_size=LOTE)
        if alterados:
            Procedimento.objects.bulk_update(alterados, ['nome', 'complexidade', 'sexo', 'idade_minima',
                                                         'idade_maxima', 'valor_sh', 'valor_sa', 'valor_sp',
                                                         'competencia', 'ativo'], batch_size=LOTE)
        # procedimentos que saíram da tabela vigente ficam inativos
        inativados = Procedimento.objects.filter(clinica=clinica, origem='sus', ativo=True).exclude(
            codigo__in=vistos).update(ativo=False)
    return {'novos': len(novos), 'atualizados': len(alterados), 'inativados': inativados}


# ------------------------------------------------------------------ CID-10
def _formatar_cid(cod):
    cod = cod.strip().upper().replace('.', '')
    return f'{cod[:3]}.{cod[3:]}' if len(cod) > 3 else cod


def _ler_cid_csv(texto):
    amostra = texto[:3000]
    delim = ';' if amostra.count(';') >= amostra.count(',') else ','
    leitor = csv.reader(io.StringIO(texto), delimiter=delim)
    cab = [norm(x) for x in next(leitor, [])]
    i_cod = next((i for i, x in enumerate(cab) if x in ('SUBCAT', 'CAT', 'CODIGO', 'COD', 'CID')), None)
    i_desc = next((i for i, x in enumerate(cab) if x in ('DESCRICAO', 'NOME', 'DESCR')), None)
    if i_cod is None or i_desc is None:
        raise ErroImportacao('CSV de CID sem colunas reconhecidas (SUBCAT/CAT/codigo e DESCRICAO/nome).')
    i_sexo = next((i for i, x in enumerate(cab) if x == 'RESTRSEXO'), None)
    for row in leitor:
        if len(row) > max(i_cod, i_desc) and row[i_cod].strip():
            sexo = row[i_sexo].strip().upper()[:1] if i_sexo is not None and i_sexo < len(row) else ''
            yield row[i_cod], row[i_desc], sexo


def _ler_cid11(linhas):
    """Planilha 'Simple Tabulation' da OMS (colunas Code, Title, ClassKind...)."""
    cab = None
    for row in linhas:
        if cab is None:
            nomes = [norm(c) for c in row]
            if 'CODE' in nomes and 'TITLE' in nomes:
                cab = {n: i for i, n in enumerate(nomes)}
            continue
        i_c, i_t = cab['CODE'], cab['TITLE']
        if len(row) <= max(i_c, i_t):
            continue
        cod = _texto(row[i_c], 20)
        if not cod:
            continue
        titulo = re.sub(r'^[\s\-]+', '', _texto(row[i_t]))
        yield cod, titulo, ''


def importar_cid(arquivo, versao='10'):
    """CID-10: CID10CSV.zip do DATASUS. CID-11: Simple Tabulation da OMS. Ou CSV codigo;descricao."""
    from .models import Cid
    if versao == '11':
        return _importar_cid11(arquivo)
    dados = arquivo.read()
    textos = []

    def decodificar(b):
        for enc in ('utf-8-sig', 'latin-1'):
            try:
                return b.decode(enc)
            except UnicodeDecodeError:
                continue
        return b.decode('latin-1', 'ignore')

    if arquivo.name.lower().endswith('.zip'):
        try:
            z = zipfile.ZipFile(io.BytesIO(dados))
        except zipfile.BadZipFile as e:
            raise ErroImportacao('Arquivo ZIP inválido.') from e
        for n in z.namelist():
            base = n.upper().split('/')[-1]
            if base.endswith('.CSV') and ('SUBCATEGORIAS' in base or 'CATEGORIAS' in base):
                textos.append(decodificar(z.read(n)))
        if not textos:
            raise ErroImportacao('O ZIP não contém CID-10-CATEGORIAS.CSV / CID-10-SUBCATEGORIAS.CSV.')
    elif arquivo.name.lower().endswith(('.csv', '.txt')):
        textos.append(decodificar(dados))
    else:
        raise ErroImportacao('Envie o CID10CSV.zip do DATASUS ou um arquivo .csv.')

    registros = {}
    for texto in textos:
        for cod, desc, sexo in _ler_cid_csv(texto):
            c = _formatar_cid(cod)
            registros[c] = (desc.strip()[:300], sexo if sexo in ('M', 'F') else '')
    return _gravar_cid(registros, '10')


def _importar_cid11(arquivo):
    nome = arquivo.name.lower()
    if nome.endswith('.zip'):
        z = zipfile.ZipFile(io.BytesIO(arquivo.read()))
        alvo = next((n for n in z.namelist() if n.lower().endswith(('.txt', '.xlsx', '.csv', '.tsv'))), None)
        if not alvo:
            raise ErroImportacao('ZIP sem planilha da CID-11.')
        from django.core.files.uploadedfile import SimpleUploadedFile
        arquivo = SimpleUploadedFile(alvo.split('/')[-1], z.read(alvo))
        nome = arquivo.name.lower()
    if nome.endswith('.tsv'):
        arquivo.name = arquivo.name[:-4] + '.txt'
    linhas = list(ler_linhas(arquivo))
    registros = {cod: (t[:300], '') for cod, t, _ in _ler_cid11(iter(linhas))}
    if not registros and linhas:
        for row in linhas[1:]:
            if len(row) >= 2 and str(row[0]).strip():
                registros[_texto(row[0], 20)] = (_texto(row[1], 300), '')
    if not registros:
        raise ErroImportacao('Nenhum código CID-11 encontrado (esperado: colunas Code e Title).')
    return _gravar_cid(registros, '11')


def _gravar_cid(registros, versao):
    from .models import Cid
    existentes = {c.codigo: c for c in Cid.objects.filter(versao=versao)}
    novos, alterados = [], []
    for cod, (nome, sexo) in registros.items():
        obj = existentes.get(cod)
        campos = {'nome': nome, 'sexo': sexo, 'categoria': cod[:4 if versao == '11' else 3],
                  'subcategoria': '.' in cod or (versao == '10' and len(cod) > 3), 'ativo': True}
        if obj:
            for k, v in campos.items():
                setattr(obj, k, v)
            alterados.append(obj)
        else:
            novos.append(Cid(versao=versao, codigo=cod, **campos))
    with transaction.atomic():
        Cid.objects.bulk_create(novos, batch_size=LOTE)
        if alterados:
            Cid.objects.bulk_update(alterados, ['nome', 'sexo', 'categoria', 'subcategoria', 'ativo'],
                                    batch_size=LOTE)
    return {'novos': len(novos), 'atualizados': len(alterados)}


def importar_procedimentos_csv(clinica, arquivo, origem='tuss'):
    linhas = ler_linhas(arquivo)
    cab = [norm(x) for x in next(linhas, [])]
    try:
        i_cod = next(i for i, x in enumerate(cab) if x.startswith('COD'))
        i_nome = next(i for i, x in enumerate(cab) if x.startswith(('NOME', 'DESCRI', 'PROCED', 'TERMO')))
    except StopIteration as e:
        raise ErroImportacao('O CSV precisa das colunas "codigo" e "nome" (ou "descricao"). '
                             'Coluna "valor" é opcional.') from e
    i_val = next((i for i, x in enumerate(cab) if x.startswith(('VALOR', 'PRECO'))), None)
    existentes = {p.codigo: p for p in Procedimento.objects.filter(clinica=clinica, origem=origem)}
    novos, alterados, vistos = [], [], set()
    for row in linhas:
        if len(row) <= max(i_cod, i_nome):
            continue
        cod = _texto(row[i_cod], 20)
        if not cod or cod in vistos:
            continue
        vistos.add(cod)
        nome = _texto(row[i_nome], 300)
        valor = decimal_br(row[i_val]) if i_val is not None and i_val < len(row) else None
        obj = existentes.get(cod)
        if obj:
            obj.nome = nome
            if valor is not None:
                obj.valor_particular = valor
            alterados.append(obj)
        else:
            novos.append(Procedimento(clinica=clinica, origem=origem, codigo=cod, nome=nome, valor_particular=valor))
    with transaction.atomic():
        Procedimento.objects.bulk_create(novos, batch_size=LOTE)
        if alterados:
            Procedimento.objects.bulk_update(alterados, ['nome', 'valor_particular'], batch_size=LOTE)
    return {'novos': len(novos), 'atualizados': len(alterados)}
