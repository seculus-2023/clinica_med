from datetime import timedelta

from django.contrib import messages
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from contas.crud import ClinicaModelForm, Crud
from contas.permissoes import acesso, tem_permissao

from .models import FORMAS_PAGAMENTO, CategoriaFinanceira, Lancamento


class LancamentoForm(ClinicaModelForm):
    class Meta:
        model = Lancamento
        exclude = []


class CategoriaForm(ClinicaModelForm):
    class Meta:
        model = CategoriaFinanceira
        exclude = []


class LancamentoCrud(Crud):
    model, form_class = Lancamento, LancamentoForm
    modulo = 'financeiro'
    nome, nome_plural, url, icone = 'Lançamento', 'Lançamentos', 'financeiro:lancamento', 'bi-cash-coin'
    url_sucesso = 'financeiro:lancamentos'
    colunas = [('vencimento', 'Vencimento'), ('descricao', 'Descrição'), ('valor', 'Valor', 'moeda'),
               ('status', 'Status')]

    @classmethod
    def antes_salvar(cls, request, obj, form):
        obj.criado_por = obj.criado_por or request.user


class CategoriaCrud(Crud):
    model, form_class = CategoriaFinanceira, CategoriaForm
    modulo = 'financeiro'
    nome, nome_plural, url, icone = 'Categoria', 'Categorias financeiras', 'financeiro:categoria', 'bi-bookmarks'
    colunas = [('nome', 'Nome'), ('tipo', 'Tipo'), ('ativo', 'Ativo')]
    busca = ['nome']
    filtros = [('tipo', 'Tipo', [('receita', 'Receita'), ('despesa', 'Despesa')])]


def _periodo(request):
    hoje = timezone.localdate()
    ini = parse_date(request.GET.get('de', '')) or hoje.replace(day=1)
    fim = parse_date(request.GET.get('ate', '')) or (ini.replace(day=28) + timedelta(days=4)).replace(day=1) - \
        timedelta(days=1)
    return ini, fim


@acesso('financeiro')
def lancamentos(request):
    ini, fim = _periodo(request)
    qs = Lancamento.objects.filter(clinica=request.clinica, vencimento__range=(ini, fim)).select_related(
        'categoria', 'paciente')
    tipo, status, q = request.GET.get('tipo', ''), request.GET.get('status', ''), request.GET.get('q', '').strip()
    if tipo:
        qs = qs.filter(tipo=tipo)
    if status == 'atrasado':
        qs = qs.filter(status='pendente', vencimento__lt=timezone.localdate())
    elif status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(descricao__icontains=q) | Q(paciente__nome__icontains=q) | Q(fornecedor__icontains=q))
    ativos = qs.exclude(status='cancelado')

    def soma(f):
        return ativos.filter(**f).aggregate(s=Sum('valor'))['s'] or 0
    totais = {
        'receber': soma({'tipo': 'receita', 'status': 'pendente'}),
        'recebido': soma({'tipo': 'receita', 'status': 'pago'}),
        'pagar': soma({'tipo': 'despesa', 'status': 'pendente'}),
        'pago': soma({'tipo': 'despesa', 'status': 'pago'}),
    }
    totais['saldo'] = totais['recebido'] - totais['pago']
    totais['previsto'] = totais['receber'] + totais['recebido'] - totais['pagar'] - totais['pago']
    return render(request, 'financeiro/lancamentos.html', {
        'lancamentos': qs.order_by('vencimento', 'id'), 'de': ini, 'ate': fim, 'tipo': tipo, 'status': status,
        'q': q, 't': totais, 'formas': FORMAS_PAGAMENTO[1:],
        'pode_editar': tem_permissao(request, 'financeiro', 'editar')})


@acesso('financeiro', 'editar')
@require_POST
def baixar(request, pk):
    lan = get_object_or_404(Lancamento, pk=pk, clinica=request.clinica)
    if request.POST.get('estornar'):
        lan.status, lan.data_pagamento, lan.valor_pago = 'pendente', None, None
        messages.info(request, 'Baixa estornada.')
    else:
        lan.status = 'pago'
        lan.data_pagamento = parse_date(request.POST.get('data', '')) or timezone.localdate()
        lan.forma_pagamento = request.POST.get('forma') or lan.forma_pagamento
        lan.valor_pago = None
        messages.success(request, f'"{lan.descricao}" baixado como pago.')
    if request.POST.get('estornar'):
        lan.caixa = None
    lan.save()
    from .gestao import vincular_caixa
    vincular_caixa(request, lan)
    prox = request.POST.get('next', '')
    return redirect(prox if prox.startswith('/') else 'financeiro:lancamentos')


@acesso('financeiro')
def fluxo_caixa(request):
    hoje = timezone.localdate()
    ini = parse_date(request.GET.get('de', '')) or hoje.replace(month=1, day=1)
    fim = parse_date(request.GET.get('ate', '')) or hoje.replace(month=12, day=31)
    base = Lancamento.objects.filter(clinica=request.clinica, vencimento__range=(ini, fim)).exclude(
        status='cancelado')
    meses = {}
    for r in base.annotate(mes=TruncMonth('vencimento')).values('mes', 'tipo', 'status').annotate(s=Sum('valor')):
        m = meses.setdefault(r['mes'], {'receita_prev': 0, 'receita_real': 0, 'despesa_prev': 0,
                                        'despesa_real': 0})
        m[f"{r['tipo']}_prev"] += r['s']
        if r['status'] == 'pago':
            m[f"{r['tipo']}_real"] += r['s']
    linhas = []
    acumulado = 0
    for mes in sorted(meses):
        m = meses[mes]
        m['saldo'] = m['receita_real'] - m['despesa_real']
        acumulado += m['saldo']
        m['acumulado'] = acumulado
        linhas.append((mes, m))
    categorias = base.filter(status='pago').values('tipo', 'categoria__nome').annotate(s=Sum('valor')).order_by(
        'tipo', '-s')
    formas = base.filter(status='pago', tipo='receita').values('forma_pagamento').annotate(s=Sum('valor'))
    nomes_formas = dict(FORMAS_PAGAMENTO)
    return render(request, 'financeiro/fluxo.html', {
        'linhas': linhas, 'de': ini, 'ate': fim, 'categorias': categorias,
        'formas': [(nomes_formas.get(f['forma_pagamento']) or 'Não informado', f['s']) for f in formas]})
