"""Caixa diário, recibos, orçamentos e DRE."""
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Q, Sum
from django.db.models.functions import TruncMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from contas.crud import ClinicaModelForm, FormSimples, estilizar_campos
from contas.permissoes import acesso, tem_permissao

from .extenso import por_extenso
from .models import FORMAS_PAGAMENTO, Caixa, ItemOrcamento, Lancamento, Orcamento


# ------------------------------------------------------------------ caixa diário
class AberturaForm(FormSimples):
    valor_abertura = forms.DecimalField(label='Troco inicial (R$)', max_digits=12, decimal_places=2, initial=0)


class FechamentoForm(FormSimples):
    valor_informado = forms.DecimalField(label='Dinheiro contado na gaveta (R$)', max_digits=12, decimal_places=2)
    observacoes = forms.CharField(label='Observações', widget=forms.Textarea, required=False)


@acesso('financeiro', 'editar')
def caixa(request):
    atual = Caixa.aberto_do_usuario(request.clinica, request.user)
    if request.method == 'POST':
        if request.POST.get('acao') == 'abrir' and not atual:
            f = AberturaForm(request.POST)
            if f.is_valid():
                Caixa.objects.create(clinica=request.clinica, usuario=request.user,
                                     valor_abertura=f.cleaned_data['valor_abertura'])
                messages.success(request, 'Caixa aberto. As baixas que você fizer entram neste caixa.')
        elif request.POST.get('acao') == 'fechar' and atual:
            f = FechamentoForm(request.POST)
            if f.is_valid():
                atual.valor_informado = f.cleaned_data['valor_informado']
                atual.observacoes = f.cleaned_data['observacoes']
                atual.fechado_em = timezone.now()
                atual.save()
                r = atual.resumo()
                messages.success(request, f"Caixa fechado. Diferença: R$ {r['diferenca']:.2f}".replace('.', ','))
                return redirect('financeiro:caixa_detalhe', atual.pk)
        return redirect('financeiro:caixa')
    ctx = {'atual': atual, 'abrir': AberturaForm(), 'fechar': FechamentoForm(),
           'historico': Caixa.objects.filter(clinica=request.clinica).select_related('usuario')[:30]}
    if atual:
        ctx['r'] = atual.resumo()
        ctx['movs'] = atual.movimentos.select_related('paciente').order_by('-data_pagamento', '-id')
    return render(request, 'financeiro/caixa.html', ctx)


@acesso('financeiro')
def caixa_detalhe(request, pk):
    cx = get_object_or_404(Caixa.objects.select_related('usuario'), pk=pk, clinica=request.clinica)
    return render(request, 'financeiro/caixa_detalhe.html', {'cx': cx, 'r': cx.resumo(),
                                                             'movs': cx.movimentos.select_related('paciente')})


def vincular_caixa(request, lan):
    """Chamado ao baixar um lançamento: liga ao caixa aberto do usuário."""
    if lan.status == 'pago' and not lan.caixa_id:
        cx = Caixa.aberto_do_usuario(request.clinica, request.user)
        if cx:
            lan.caixa = cx
            lan.save(update_fields=['caixa', 'atualizado_em'])


# ------------------------------------------------------------------ recibo
@acesso('financeiro')
def recibo(request, pk):
    lan = get_object_or_404(Lancamento.objects.select_related('paciente', 'medico', 'clinica'), pk=pk,
                            clinica=request.clinica, tipo='receita')
    if lan.status != 'pago':
        messages.warning(request, 'O recibo só pode ser emitido para lançamentos pagos.')
        return redirect('financeiro:lancamentos')
    valor = lan.valor_pago or lan.valor
    return render(request, 'financeiro/recibo.html', {
        'lan': lan, 'c': lan.clinica, 'valor': valor, 'extenso': por_extenso(valor),
        'forma': dict(FORMAS_PAGAMENTO).get(lan.forma_pagamento, '')})


# ------------------------------------------------------------------ orçamentos
class OrcamentoForm(ClinicaModelForm):
    class Meta:
        model = Orcamento
        fields = ['paciente', 'medico', 'data', 'validade', 'desconto', 'parcelas', 'status', 'observacoes']


class ItemForm(forms.ModelForm):
    class Meta:
        model = ItemOrcamento
        fields = ['tipo', 'descricao', 'quantidade', 'valor_unitario']

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        from cadastros.models import TipoAtendimento
        self.fields['tipo'].queryset = TipoAtendimento.objects.filter(clinica=clinica, ativo=True)
        self.fields['valor_unitario'].required = False
        self.fields['valor_unitario'].help_text = 'Vazio = valor da tabela de preços'
        estilizar_campos(self)

    def clean_valor_unitario(self):
        return self.cleaned_data.get('valor_unitario') or 0


ItensFormSet = forms.inlineformset_factory(Orcamento, ItemOrcamento, form=ItemForm, extra=3, can_delete=True)


@acesso('financeiro')
def orcamentos(request):
    qs = Orcamento.objects.filter(clinica=request.clinica).select_related('paciente', 'medico').prefetch_related('itens')
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    if request.GET.get('q'):
        qs = qs.filter(paciente__nome__icontains=request.GET['q'])
    return render(request, 'financeiro/orcamentos.html', {
        'orcamentos': qs[:200], 'status': Orcamento.STATUS, 'f': request.GET,
        'pode_editar': tem_permissao(request, 'financeiro', 'editar')})


@acesso('financeiro', 'editar')
def orcamento_form(request, pk=None):
    orc = get_object_or_404(Orcamento, pk=pk, clinica=request.clinica) if pk else None
    inicial = {} if orc else {'paciente': request.GET.get('paciente'),
                              'validade': timezone.localdate() + timezone.timedelta(days=15)}
    form = OrcamentoForm(request.POST or None, instance=orc, initial=inicial, clinica=request.clinica)
    itens = ItensFormSet(request.POST or None, instance=orc or Orcamento(), form_kwargs={'clinica': request.clinica})
    if request.method == 'POST' and form.is_valid() and itens.is_valid():
        with transaction.atomic():
            o = form.save(commit=False)
            if not o.pk:
                o.clinica, o.criado_por = request.clinica, request.user
            o.save()
            itens.instance = o
            for it in itens.save(commit=False):
                if it.tipo_id and not it.valor_unitario:
                    it.valor_unitario = it.tipo.valor
                if it.tipo_id or it.descricao:
                    it.save()
            for it in itens.deleted_objects:
                it.delete()
        messages.success(request, 'Orçamento salvo.')
        return redirect('financeiro:orcamento_imprimir', o.pk) if request.POST.get('imprimir') else redirect(
            'financeiro:orcamentos')
    precos = {}
    from cadastros.models import TipoAtendimento
    for t in TipoAtendimento.objects.filter(clinica=request.clinica, ativo=True):
        precos[t.pk] = str(t.valor)
    import json
    return render(request, 'financeiro/orcamento_form.html', {'form': form, 'itens': itens, 'obj': orc,
                                                              'precos': json.dumps(precos)})


@acesso('financeiro')
def orcamento_imprimir(request, pk):
    o = get_object_or_404(Orcamento.objects.select_related('paciente', 'medico', 'clinica'), pk=pk,
                          clinica=request.clinica)
    return render(request, 'financeiro/orcamento_imprimir.html', {'o': o, 'c': o.clinica, 'extenso': por_extenso(o.total)})


@acesso('financeiro', 'editar')
@require_POST
def orcamento_aprovar(request, pk):
    o = get_object_or_404(Orcamento, pk=pk, clinica=request.clinica)
    if o.status == 'aprovado':
        messages.info(request, 'Orçamento já aprovado.')
    elif not o.total:
        messages.warning(request, 'Orçamento sem valor.')
    else:
        with transaction.atomic():
            lans = Lancamento.gerar_parcelas(clinica=request.clinica, descricao=f'Orçamento {o.pk} - {o.paciente}',
                                             total=o.total, parcelas=o.parcelas or 1, primeiro_vencimento=timezone.localdate(),
                                             paciente=o.paciente, usuario=request.user, categoria='Procedimentos',
                                             medico=o.medico)
            Lancamento.objects.filter(pk__in=[x.pk for x in lans]).update(orcamento=o)
            o.status = 'aprovado'
            o.save(update_fields=['status', 'atualizado_em'])
        messages.success(request, f'Orçamento aprovado: {len(lans)} parcela(s) lançada(s) no contas a receber.')
    return redirect('financeiro:orcamentos')


# ------------------------------------------------------------------ DRE
def montar_dre(clinica, ini, fim, regime='caixa'):
    """Demonstração do resultado: receitas e despesas por categoria e mês (regime de caixa ou competência)."""
    base = Lancamento.objects.filter(clinica=clinica).exclude(status='cancelado')
    if regime == 'caixa':
        base = base.filter(status='pago', data_pagamento__range=(ini, fim))
        campo_data, campo_valor = 'data_pagamento', 'valor_pago'
    else:
        base = base.filter(vencimento__range=(ini, fim))
        campo_data, campo_valor = 'vencimento', 'valor'
    meses = sorted({m for m in base.annotate(m=TruncMonth(campo_data)).values_list('m', flat=True) if m})
    linhas = {'receita': {}, 'despesa': {}}
    for r in base.annotate(m=TruncMonth(campo_data)).values('tipo', 'categoria__nome', 'm').annotate(
            s=Sum(campo_valor), s2=Sum('valor')):
        cat = r['categoria__nome'] or 'Sem categoria'
        linhas[r['tipo']].setdefault(cat, {})[r['m']] = (r['s'] if r['s'] is not None else r['s2']) or Decimal('0')

    def bloco(tipo):
        out = []
        for cat in sorted(linhas[tipo]):
            vals = [linhas[tipo][cat].get(m, Decimal('0')) for m in meses]
            out.append((cat, vals, sum(vals, Decimal('0'))))
        tot = [sum((v[1][i] for v in out), Decimal('0')) for i in range(len(meses))]
        return out, tot, sum(tot, Decimal('0'))
    rec, rec_m, rec_t = bloco('receita')
    desp, desp_m, desp_t = bloco('despesa')
    resultado = [a - b for a, b in zip(rec_m, desp_m)]
    margem = (rec_t - desp_t) * 100 / rec_t if rec_t else None
    return {'meses': meses, 'receitas': rec, 'rec_m': rec_m, 'rec_t': rec_t, 'despesas': desp, 'desp_m': desp_m,
            'desp_t': desp_t, 'resultado': resultado, 'resultado_t': rec_t - desp_t, 'margem': margem}


@acesso('financeiro')
def dre(request):
    hoje = timezone.localdate()
    ini = parse_date(request.GET.get('de', '')) or hoje.replace(month=1, day=1)
    fim = parse_date(request.GET.get('ate', '')) or hoje
    regime = request.GET.get('regime', 'caixa')
    d = montar_dre(request.clinica, ini, fim, regime)
    if request.GET.get('formato') == 'xlsx':
        from painel.exportar import xlsx_resposta
        cab = ['Conta'] + [m.strftime('%m/%Y') for m in d['meses']] + ['Total']
        linhas = [['RECEITAS'] + [''] * (len(d['meses']) + 1)]
        linhas += [[c] + v + [t] for c, v, t in d['receitas']]
        linhas.append(['Total de receitas'] + d['rec_m'] + [d['rec_t']])
        linhas.append(['DESPESAS'] + [''] * (len(d['meses']) + 1))
        linhas += [[c] + v + [t] for c, v, t in d['despesas']]
        linhas.append(['Total de despesas'] + d['desp_m'] + [d['desp_t']])
        linhas.append(['RESULTADO'] + d['resultado'] + [d['resultado_t']])
        return xlsx_resposta(f'DRE {ini:%d-%m-%Y} a {fim:%d-%m-%Y}', cab, linhas, f'dre_{ini}_{fim}.xlsx',
                             titulo=f'DRE - {request.clinica.nome} - {ini:%d/%m/%Y} a {fim:%d/%m/%Y} ({regime})')
    return render(request, 'financeiro/dre.html', {'d': d, 'de': ini, 'ate': fim, 'regime': regime})
