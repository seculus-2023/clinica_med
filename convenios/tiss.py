"""Geração do XML de lote TISS (mensagem ENVIO_LOTE_GUIAS) — guias de consulta e SP/SADT.

Estrutura baseada no Padrão TISS da ANS (componente de comunicação, versão 4.01.00). O hash do epílogo é o MD5 da
concatenação de todos os conteúdos de texto da mensagem, como define o padrão.
ATENÇÃO: cada operadora valida o XML contra o schema (XSD) da versão; teste o arquivo no validador/portal da
operadora antes do primeiro envio e ajuste dados cadastrais (CNES, código do prestador, CBO) se houver rejeição.
"""
import hashlib
import xml.etree.ElementTree as ET
from decimal import Decimal

from django.utils import timezone

NS = 'http://www.ans.gov.br/padroes/tiss/schemas'
CONSELHOS = {'CRAS': '01', 'COREN': '02', 'CRF': '03', 'CRFA': '04', 'CREFITO': '05', 'CRM': '06', 'CRN': '07',
             'CRO': '08', 'CRP': '09'}
UF_IBGE = {'RO': '11', 'AC': '12', 'AM': '13', 'RR': '14', 'PA': '15', 'AP': '16', 'TO': '17', 'MA': '21', 'PI': '22',
           'CE': '23', 'RN': '24', 'PB': '25', 'PE': '26', 'AL': '27', 'SE': '28', 'BA': '29', 'MG': '31', 'ES': '32',
           'RJ': '33', 'SP': '35', 'PR': '41', 'SC': '42', 'RS': '43', 'MS': '50', 'MT': '51', 'GO': '52', 'DF': '53'}


def _q(tag):
    return f'{{{NS}}}{tag}'


def _el(pai, tag, texto=None):
    e = ET.SubElement(pai, _q(tag))
    if texto is not None:
        e.text = str(texto)
    return e


def _valor(v):
    return f'{Decimal(v or 0):.2f}'


def _digitos(s):
    return ''.join(c for c in str(s or '') if c.isdigit())


def _profissional(pai, tag, medico):
    p = _el(pai, tag)
    _el(p, 'nomeProfissional', medico.nome[:70])
    _el(p, 'conselhoProfissional', CONSELHOS.get((medico.conselho or 'CRM').upper(), '10'))
    _el(p, 'numeroConselhoProfissional', _digitos(medico.registro)[:15] or '0')
    _el(p, 'UF', UF_IBGE.get(medico.uf_registro or '', '35'))
    _el(p, 'CBOS', medico.cbo or ('223605' if (medico.conselho or '').upper() == 'CREFITO' else '225125'))
    return p


def _contratado(pai, tag, lote):
    c = _el(pai, tag)
    _el(c, 'codigoPrestadorNaOperadora', lote.operadora.codigo_prestador or _digitos(lote.clinica.cnpj))
    return c


def _guia_consulta(pai, g, lote):
    gc = _el(pai, 'guiaConsulta')
    cab = _el(gc, 'cabecalhoConsulta')
    _el(cab, 'registroANS', lote.operadora.registro_ans)
    _el(cab, 'numeroGuiaPrestador', g.numero_guia)
    if g.numero_guia_operadora:
        _el(gc, 'numeroGuiaOperadora', g.numero_guia_operadora)
    ben = _el(gc, 'dadosBeneficiario')
    _el(ben, 'numeroCarteira', g.carteirinha)
    _el(ben, 'atendimentoRN', 'N')
    ce = _contratado(gc, 'contratadoExecutante', lote)
    _el(ce, 'CNES', lote.clinica.cnes or '9999999')
    _profissional(gc, 'profissionalExecutante', g.medico)
    _el(gc, 'indicacaoAcidente', '9')
    at = _el(gc, 'dadosAtendimento')
    _el(at, 'regimeAtendimento', '01')
    _el(at, 'dataAtendimento', g.data_atendimento.isoformat())
    _el(at, 'tipoConsulta', g.tipo_consulta)
    proc = _el(at, 'procedimento')
    _el(proc, 'codigoTabela', g.codigo_tabela)
    _el(proc, 'codigoProcedimento', g.codigo_procedimento)
    _el(proc, 'valorProcedimento', _valor(g.valor_total))


def _guia_sadt(pai, g, lote):
    gs = _el(pai, 'guiaSP-SADT')
    cab = _el(gs, 'cabecalhoGuia')
    _el(cab, 'registroANS', lote.operadora.registro_ans)
    _el(cab, 'numeroGuiaPrestador', g.numero_guia)
    if g.senha or g.numero_guia_operadora:
        aut = _el(gs, 'dadosAutorizacao')
        if g.numero_guia_operadora:
            _el(aut, 'numeroGuiaOperadora', g.numero_guia_operadora)
        _el(aut, 'dataAutorizacao', (g.data_autorizacao or g.data_atendimento).isoformat())
        if g.senha:
            _el(aut, 'senha', g.senha)
    ben = _el(gs, 'dadosBeneficiario')
    _el(ben, 'numeroCarteira', g.carteirinha)
    _el(ben, 'atendimentoRN', 'N')
    sol = _el(gs, 'dadosSolicitante')
    _contratado(sol, 'contratadoSolicitante', lote)
    _profissional(sol, 'profissionalSolicitante', g.medico)
    sc = _el(gs, 'dadosSolicitacao')
    _el(sc, 'caraterAtendimento', g.carater)
    if g.indicacao_clinica:
        _el(sc, 'indicacaoClinica', g.indicacao_clinica[:500])
    ex = _el(gs, 'dadosExecutante')
    _contratado(ex, 'contratadoExecutante', lote)
    _el(ex, 'CNES', lote.clinica.cnes or '9999999')
    at = _el(gs, 'dadosAtendimento')
    _el(at, 'tipoAtendimento', '05')
    _el(at, 'indicacaoAcidente', '9')
    _el(at, 'regimeAtendimento', '01')
    pe = _el(_el(gs, 'procedimentosExecutados'), 'procedimentoExecutado')
    _el(pe, 'sequencialItem', '1')
    _el(pe, 'dataExecucao', g.data_atendimento.isoformat())
    pr = _el(pe, 'procedimento')
    _el(pr, 'codigoTabela', g.codigo_tabela)
    _el(pr, 'codigoProcedimento', g.codigo_procedimento)
    _el(pr, 'descricaoProcedimento', g.descricao_procedimento[:150])
    _el(pe, 'quantidadeExecutada', g.quantidade)
    _el(pe, 'reducaoAcrescimo', '1.00')
    _el(pe, 'valorUnitario', _valor(g.valor_unitario))
    _el(pe, 'valorTotal', _valor(g.valor_total))
    eq = _el(pe, 'equipeSadt')
    _el(eq, 'grauPart', '12')
    cp = _el(eq, 'codProfissional')
    _el(cp, 'codigoPrestadorNaOperadora', lote.operadora.codigo_prestador or _digitos(lote.clinica.cnpj))
    _el(eq, 'nomeProf', g.medico.nome[:70])
    _el(eq, 'conselho', CONSELHOS.get((g.medico.conselho or 'CRM').upper(), '10'))
    _el(eq, 'numeroConselhoProfissional', _digitos(g.medico.registro)[:15] or '0')
    _el(eq, 'UF', UF_IBGE.get(g.medico.uf_registro or '', '35'))
    _el(eq, 'CBOS', g.medico.cbo or '225125')
    tot = _el(gs, 'valorTotal')
    _el(tot, 'valorProcedimentos', _valor(g.valor_total))
    _el(tot, 'valorTotalGeral', _valor(g.valor_total))


def _textos(e):
    partes = [e.text or '']
    for filho in e:
        partes.extend(_textos(filho))
    return partes


def gerar_xml(lote):
    ET.register_namespace('ans', NS)
    raiz = ET.Element(_q('mensagemTISS'))
    agora = timezone.localtime()
    cab = _el(raiz, 'cabecalho')
    idt = _el(cab, 'identificacaoTransacao')
    _el(idt, 'tipoTransacao', 'ENVIO_LOTE_GUIAS')
    _el(idt, 'sequencialTransacao', lote.numero)
    _el(idt, 'dataRegistroTransacao', agora.date().isoformat())
    _el(idt, 'horaRegistroTransacao', agora.strftime('%H:%M:%S'))
    _contratado(_el(cab, 'origem'), 'identificacaoPrestador', lote)
    _el(_el(cab, 'destino'), 'registroANS', lote.operadora.registro_ans)
    _el(cab, 'Padrao', lote.operadora.versao_tiss or '4.01.00')
    lg = _el(_el(raiz, 'prestadorParaOperadora'), 'loteGuias')
    _el(lg, 'numeroLote', lote.numero)
    guias = _el(lg, 'guiasTISS')
    for g in lote.guias.select_related('medico', 'paciente').order_by('id'):
        (_guia_consulta if g.tipo == 'consulta' else _guia_sadt)(guias, g, lote)
    epi = _el(raiz, 'epilogo')
    hash_md5 = hashlib.md5(''.join(_textos(raiz)).encode('iso-8859-1', 'replace')).hexdigest()
    _el(epi, 'hash', hash_md5)
    corpo = ET.tostring(raiz, encoding='unicode')
    xml = '<?xml version="1.0" encoding="ISO-8859-1"?>\n' + corpo
    return xml.encode('iso-8859-1', 'replace'), hash_md5


def validar_lote(lote):
    """Pendências cadastrais que fazem a operadora rejeitar o lote."""
    erros = []
    op = lote.operadora
    if len(_digitos(op.registro_ans)) != 6:
        erros.append(f'Operadora {op}: registro ANS deve ter 6 dígitos.')
    if not op.codigo_prestador:
        erros.append(f'Operadora {op}: informe o código do prestador (código da clínica na operadora).')
    if not lote.clinica.cnes:
        erros.append('Clínica sem CNES (Configurações da clínica).')
    for g in lote.guias.select_related('medico'):
        if not g.carteirinha:
            erros.append(f'Guia {g.numero_guia}: número da carteira vazio.')
        if not g.codigo_procedimento:
            erros.append(f'Guia {g.numero_guia}: código do procedimento vazio.')
        if not g.medico.registro:
            erros.append(f'Guia {g.numero_guia}: profissional {g.medico} sem número de conselho.')
    return erros
