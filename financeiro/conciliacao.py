"""Conciliação bancária: importação de extrato (OFX ou CSV) e casamento com os lançamentos."""
import hashlib
import re
from datetime import date, timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from cadastros.importacao import ErroImportacao, decimal_br, ler_linhas, norm
from contas.crud import ClinicaModelForm, Crud, FormSimples
from contas.permissoes import acesso

from .models import ContaBancaria, Lancamento, TransacaoBancaria

TOLERANCIA_DIAS = 5


class ContaForm(ClinicaModelForm):
    class Meta:
        model = ContaBancaria
        exclude = []


class ContaCrud(Crud):
    model, form_class = ContaBancaria, ContaForm
    modulo = 'financeiro'
    nome, nome_plural, url, icone = 'Conta bancária', 'Contas bancárias', 'financeiro:conta', 'bi-bank'
    colunas = [('nome', 'Conta'), ('banco', 'Banco'), ('agencia', 'Agência'), ('numero', 'Número'), ('ativo', 'Ativa')]
    acoes_linha = [('financeiro:conciliacao', 'bi-check2-square', 'Conciliar')]


# ------------------------------------------------------------------ leitura do extrato
def _data_ofx(s):
    s = re.sub(r'\D', '', s)[:8]
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def ler_ofx(texto):
    """Lê blocos <STMTTRN> de arquivos OFX (SGML 1.x ou XML 2.x)."""
    itens = []
    for bloco in re.split(r'<STMTTRN>', texto, flags=re.I)[1:]:
        bloco = re.split(r'</STMTTRN>|</BANKTRANLIST>', bloco, flags=re.I)[0]

        def tag(nome, bloco=bloco):
            m = re.search(rf'<{nome}>([^<\r\n]*)', bloco, re.I)
            return m.group(1).strip() if m else ''
        if not tag('DTPOSTED') or not tag('TRNAMT'):
            continue
        valor = Decimal(tag('TRNAMT').replace(',', '.'))
        desc = ' '.join(x for x in (tag('NAME'), tag('MEMO')) if x)[:250]
        data = _data_ofx(tag('DTPOSTED'))
        fitid = tag('FITID') or hashlib.md5(f'{data}{valor}{desc}'.encode()).hexdigest()
        itens.append({'data': data, 'valor': valor, 'descricao': desc, 'fitid': fitid[:120]})
    return itens


def ler_csv(arquivo):
    """CSV/XLSX com colunas data;descricao;valor (ou credito/debito)."""
    linhas = ler_linhas(arquivo)
    cab = [norm(c) for c in next(linhas, [])]
    idx = lambda *n: next((i for i, c in enumerate(cab) if any(c.startswith(x) for x in n)), None)  # noqa: E731
    i_d, i_h, i_v = idx('DATA'), idx('DESCRI', 'HISTOR', 'LANCAMENTO'), idx('VALOR')
    i_c, i_db = idx('CREDITO', 'ENTRADA'), idx('DEBITO', 'SAIDA')
    if i_d is None or (i_v is None and i_c is None):
        raise ErroImportacao('CSV precisa das colunas "data", "descricao" e "valor" (ou "credito"/"debito").')
    itens = []
    for row in linhas:
        if len(row) <= i_d or not row[i_d]:
            continue
        bruto = row[i_d]
        if hasattr(bruto, 'date'):
            d = bruto.date() if callable(bruto.date) else bruto
        else:
            m = re.match(r'(\d{1,2})/(\d{1,2})/(\d{2,4})', str(bruto)) or re.match(r'(\d{4})-(\d{2})-(\d{2})', str(bruto))
            if not m:
                continue
            a, b, c = m.groups()
            d = date(int(a), int(b), int(c)) if len(a) == 4 else date(int(c) + (2000 if len(c) == 2 else 0), int(b), int(a))
        if i_v is not None:
            valor = decimal_br(row[i_v]) if i_v < len(row) else None
        else:
            cr = decimal_br(row[i_c]) if i_c < len(row) else None
            db = decimal_br(row[i_db]) if i_db is not None and i_db < len(row) else None
            valor = (cr or 0) - abs(db or 0)
        if not valor:
            continue
        desc = str(row[i_h]).strip()[:250] if i_h is not None and i_h < len(row) else ''
        fitid = hashlib.md5(f'{d}{valor}{desc}{len(itens)}'.encode()).hexdigest()
        itens.append({'data': d, 'valor': valor, 'descricao': desc, 'fitid': fitid})
    return itens


def importar_extrato(conta, arquivo):
    nome = arquivo.name.lower()
    if nome.endswith(('.ofx', '.qfx')):
        bruto = arquivo.read()
        texto = bruto.decode('utf-8', 'ignore') if b'UTF-8' in bruto[:500].upper() else bruto.decode('latin-1')
        itens = ler_ofx(texto)
    else:
        itens = ler_csv(arquivo)
    if not itens:
        raise ErroImportacao('Nenhuma transação encontrada no arquivo.')
    novos = 0
    for it in itens:
        _, criado = TransacaoBancaria.objects.get_or_create(
            clinica=conta.clinica, conta=conta, fitid=it['fitid'],
            defaults={'data': it['data'], 'valor': it['valor'], 'descricao': it['descricao']})
        novos += criado
    return novos, len(itens) - novos


# ------------------------------------------------------------------ casamento
def sugestoes(t):
    tipo = 'receita' if t.valor > 0 else 'despesa'
    janela = (t.data - timedelta(days=TOLERANCIA_DIAS), t.data + timedelta(days=TOLERANCIA_DIAS))
    qs = Lancamento.objects.filter(clinica=t.clinica, tipo=tipo, conciliado=False).exclude(status='cancelado').filter(
        Q(valor=abs(t.valor)) | Q(valor_pago=abs(t.valor))).filter(
        Q(vencimento__range=janela) | Q(data_pagamento__range=janela))
    return list(qs.select_related('paciente')[:5])


def conciliar(t, lan, usuario=None):
    with transaction.atomic():
        t.lancamento, t.ignorada = lan, False
        t.save(update_fields=['lancamento', 'ignorada', 'atualizado_em'])
        lan.conciliado, lan.conta = True, t.conta
        if lan.status != 'pago':
            lan.status, lan.data_pagamento, lan.valor_pago = 'pago', t.data, abs(t.valor)
            if not lan.forma_pagamento:
                lan.forma_pagamento = 'transferencia'
        lan.save()


def auto_conciliar(conta):
    n = 0
    for t in conta.transacoes.filter(lancamento__isnull=True, ignorada=False):
        s = sugestoes(t)
        if len(s) == 1:
            conciliar(t, s[0])
            n += 1
    return n


# ------------------------------------------------------------------ views
class ExtratoForm(FormSimples):
    arquivo = forms.FileField(label='Extrato (OFX, CSV ou XLSX)',
                              help_text='OFX: exporte no internet banking ("extrato para Money/Quicken/OFX"). '
                                        'CSV: colunas data;descricao;valor.')


@acesso('financeiro')
def conciliacao(request, pk):
    conta = get_object_or_404(ContaBancaria, pk=pk, clinica=request.clinica)
    form = ExtratoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            novos, repetidos = importar_extrato(conta, form.cleaned_data['arquivo'])
            auto = auto_conciliar(conta)
            messages.success(request, f'{novos} transação(ões) importada(s) ({repetidos} já existiam). '
                                      f'{auto} conciliada(s) automaticamente.')
        except (ErroImportacao, ValueError) as e:
            messages.error(request, f'Não foi possível ler o extrato: {e}')
        return redirect('financeiro:conciliacao', conta.pk)
    filtro = request.GET.get('ver', 'pendentes')
    trans = conta.transacoes.select_related('lancamento')
    if filtro == 'pendentes':
        trans = trans.filter(lancamento__isnull=True, ignorada=False)
    elif filtro == 'conciliadas':
        trans = trans.filter(lancamento__isnull=False)
    linhas = [(t, sugestoes(t) if not t.lancamento_id and not t.ignorada else []) for t in trans[:300]]
    saldo_extrato = conta.saldo_inicial + (conta.transacoes.filter(ignorada=False).aggregate(s=Sum('valor'))['s'] or 0)
    tot = conta.transacoes.count()
    pend = conta.transacoes.filter(lancamento__isnull=True, ignorada=False).count()
    return render(request, 'financeiro/conciliacao.html', {
        'conta': conta, 'form': form, 'linhas': linhas, 'ver': filtro, 'saldo_extrato': saldo_extrato,
        'total': tot, 'pendentes': pend, 'contas': ContaBancaria.objects.filter(clinica=request.clinica, ativo=True)})


@acesso('financeiro', 'editar')
@require_POST
def acao_transacao(request, pk):
    t = get_object_or_404(TransacaoBancaria, pk=pk, clinica=request.clinica)
    acao = request.POST.get('acao')
    if acao == 'conciliar':
        lan = get_object_or_404(Lancamento, pk=request.POST.get('lancamento'), clinica=request.clinica)
        conciliar(t, lan, request.user)
        messages.success(request, 'Transação conciliada.')
    elif acao == 'criar':
        tipo = 'receita' if t.valor > 0 else 'despesa'
        lan = Lancamento.objects.create(
            clinica=request.clinica, tipo=tipo, descricao=t.descricao or 'Lançamento do extrato', valor=abs(t.valor),
            vencimento=t.data, categoria=Lancamento.categoria_padrao(request.clinica, tipo, 'Extrato bancário'),
            criado_por=request.user)
        conciliar(t, lan, request.user)
        messages.success(request, 'Lançamento criado a partir do extrato e conciliado.')
    elif acao == 'ignorar':
        t.ignorada = True
        t.save(update_fields=['ignorada', 'atualizado_em'])
    elif acao == 'desfazer':
        if t.lancamento_id:
            Lancamento.objects.filter(pk=t.lancamento_id).update(conciliado=False)
        t.lancamento, t.ignorada = None, False
        t.save(update_fields=['lancamento', 'ignorada', 'atualizado_em'])
        messages.info(request, 'Conciliação desfeita (o lançamento continua pago).')
    elif acao == 'auto':
        messages.success(request, f'{auto_conciliar(t.conta)} transação(ões) conciliada(s).')
    return redirect(f"{request.POST.get('next') or '/financeiro/'}")


@acesso('financeiro')
def conciliacao_inicio(request):
    conta = ContaBancaria.objects.filter(clinica=request.clinica, ativo=True).first()
    if conta:
        return redirect('financeiro:conciliacao', conta.pk)
    messages.info(request, 'Cadastre a conta bancária para importar o extrato.')
    return redirect('financeiro:conta_novo')
