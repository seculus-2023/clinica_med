from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cadastros.models import Paciente
from contas.crud import ClinicaModelForm, Crud
from contas.permissoes import acesso, tem_permissao

from . import tiss
from .models import GuiaTISS, LoteTISS, Operadora, Plano, PrecoConvenio
from .services import proximo_lote

MOTIVOS_GLOSA = [('', '-'), ('1001', '1001 - Número da carteira inválido'), ('1002', '1002 - Número do cartão nacional de saúde inválido'),
                 ('1013', '1013 - Cadastro do beneficiário com problemas'), ('1016', '1016 - Beneficiário com atendimento suspenso'),
                 ('1301', '1301 - Tipo de guia inválido'), ('1323', '1323 - Data de atendimento inválida'),
                 ('1601', '1601 - Reapresentação de item sem alteração'), ('1702', '1702 - Cobrança de procedimento em duplicidade'),
                 ('1705', '1705 - Valor apresentado acima da tabela'), ('1801', '1801 - Procedimento inválido'),
                 ('1802', '1802 - Procedimento incompatível com o sexo'), ('1823', '1823 - Procedimento não autorizado'),
                 ('2101', '2101 - Valor apresentado diferente do contratado'), ('9999', '9999 - Outros')]


# ------------------------------------------------------------------ cadastros
class OperadoraForm(ClinicaModelForm):
    class Meta:
        model = Operadora
        exclude = []


class PlanoForm(ClinicaModelForm):
    class Meta:
        model = Plano
        exclude = []


class PrecoForm(ClinicaModelForm):
    class Meta:
        model = PrecoConvenio
        exclude = []

    def clean(self):
        d = super().clean()
        if d.get('plano') and d.get('operadora') and d['plano'].operadora_id != d['operadora'].pk:
            self.add_error('plano', 'Este plano é de outra operadora.')
        return d


class OperadoraCrud(Crud):
    model, form_class = Operadora, OperadoraForm
    modulo = 'convenios'
    nome, nome_plural, url, icone = 'Operadora', 'Convênios (operadoras)', 'convenios:operadora', 'bi-building-check'
    colunas = [('nome', 'Operadora'), ('registro_ans', 'Reg. ANS'), ('codigo_prestador', 'Cód. prestador'),
               ('versao_tiss', 'TISS'), ('prazo_pagamento_dias', 'Prazo (dias)'), ('ativo', 'Ativo')]
    busca = ['nome', 'registro_ans']
    acoes_topo = [('convenios:plano_list', 'bi-diagram-2', 'Planos'), ('convenios:preco_list', 'bi-tags', 'Tabela de preços')]


class PlanoCrud(Crud):
    model, form_class = Plano, PlanoForm
    modulo = 'convenios'
    nome, nome_plural, url, icone = 'Plano', 'Planos dos convênios', 'convenios:plano', 'bi-diagram-2'
    colunas = [('operadora', 'Operadora'), ('nome', 'Plano'), ('ativo', 'Ativo')]
    busca = ['nome', 'operadora__nome']


class PrecoCrud(Crud):
    model, form_class = PrecoConvenio, PrecoForm
    modulo = 'convenios'
    nome, nome_plural, url, icone = 'Preço', 'Tabela de preços por convênio', 'convenios:preco', 'bi-tags'
    descricao = 'Valor de cada tipo de atendimento por operadora (e plano). Usado no agendamento e nas guias TISS.'
    colunas = [('operadora', 'Operadora'), ('plano', 'Plano'), ('tipo', 'Atendimento'), ('codigo', 'TUSS'),
               ('valor', 'Valor', 'moeda'), ('requer_autorizacao', 'Autorização'), ('ativo', 'Ativo')]
    busca = ['operadora__nome', 'tipo__nome', 'codigo_tuss']

    @classmethod
    def queryset(cls, request):
        return PrecoConvenio.objects.filter(clinica=request.clinica).select_related('operadora', 'plano', 'tipo__procedimento')


@acesso(None)
def api_paciente(request, pk):
    p = get_object_or_404(Paciente, pk=pk, clinica=request.clinica)
    return JsonResponse({'operadora': p.operadora_id, 'plano': p.plano_id, 'carteirinha': p.carteirinha,
                         'validade': p.validade_carteirinha.strftime('%d/%m/%Y') if p.validade_carteirinha else '',
                         'vencida': p.carteirinha_vencida,
                         'planos': [{'id': x.pk, 'nome': x.nome} for x in Plano.objects.filter(operadora_id=p.operadora_id)]})


@acesso(None)
def api_planos(request):
    return JsonResponse([{'id': x.pk, 'nome': x.nome} for x in Plano.objects.filter(
        clinica=request.clinica, operadora_id=request.GET.get('operadora') or 0, ativo=True)], safe=False)


# ------------------------------------------------------------------ guias
class GuiaForm(ClinicaModelForm):
    class Meta:
        model = GuiaTISS
        fields = ['tipo', 'operadora', 'plano', 'numero_guia', 'numero_guia_operadora', 'senha', 'data_autorizacao',
                  'carteirinha', 'data_atendimento', 'tipo_consulta', 'carater', 'cid', 'indicacao_clinica',
                  'codigo_tabela', 'codigo_procedimento', 'descricao_procedimento', 'quantidade', 'valor_unitario',
                  'status', 'valor_pago', 'glosa_codigo', 'glosa_motivo', 'recurso', 'recurso_status']
        widgets = {'indicacao_clinica': forms.Textarea(attrs={'rows': 2}), 'recurso': forms.Textarea(attrs={'rows': 3}),
                   'glosa_codigo': forms.Select(choices=MOTIVOS_GLOSA)}


@acesso('convenios')
def guias(request):
    qs = GuiaTISS.objects.filter(clinica=request.clinica).select_related('paciente', 'operadora', 'lote')
    for campo in ('status', 'operadora', 'tipo'):
        if request.GET.get(campo):
            qs = qs.filter(**{campo: request.GET[campo]})
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(paciente__nome__icontains=q) | Q(numero_guia=q) | Q(carteirinha__icontains=q))
    tot = qs.exclude(status='cancelada').aggregate(v=Sum('valor_total'), p=Sum('valor_pago'), g=Sum('valor_glosado'))
    return render(request, 'convenios/guias.html', {
        'guias': qs[:300], 'tot': tot, 'operadoras': Operadora.objects.filter(clinica=request.clinica),
        'status': GuiaTISS.STATUS, 'f': request.GET, 'pode_editar': tem_permissao(request, 'convenios', 'editar')})


@acesso('convenios', 'editar')
def guia_form(request, pk=None):
    g = get_object_or_404(GuiaTISS, pk=pk, clinica=request.clinica) if pk else None
    form = GuiaForm(request.POST or None, instance=g, clinica=request.clinica)
    if not g:
        form.fields['paciente'] = forms.ModelChoiceField(Paciente.objects.filter(clinica=request.clinica),
                                                          widget=forms.Select(attrs={'class': 'form-select'}))
        from cadastros.models import Medico
        form.fields['medico'] = forms.ModelChoiceField(Medico.objects.filter(clinica=request.clinica, ativo=True),
                                                        label='Profissional', widget=forms.Select(attrs={'class': 'form-select'}))
        form.initial.setdefault('numero_guia', GuiaTISS.proximo_numero(request.clinica))
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        if not obj.pk:
            obj.clinica = request.clinica
            obj.paciente, obj.medico = form.cleaned_data['paciente'], form.cleaned_data['medico']
        obj.save()
        if obj.lote_id:
            obj.lote.recalcular()
        messages.success(request, 'Guia salva.')
        return redirect('convenios:guias')
    return render(request, 'form_simples.html', {'form': form, 'titulo': f'Guia TISS {g.numero_guia}' if g else 'Nova guia TISS',
                                                 'voltar': 'convenios:guias'})


@acesso('convenios')
def guia_imprimir(request, pk):
    g = get_object_or_404(GuiaTISS.objects.select_related('paciente', 'medico', 'operadora', 'plano'), pk=pk,
                          clinica=request.clinica)
    return render(request, 'convenios/guia_imprimir.html', {'g': g, 'c': request.clinica})


# ------------------------------------------------------------------ lotes
class NovoLoteForm(forms.Form):
    operadora = forms.ModelChoiceField(Operadora.objects.none(), widget=forms.Select(attrs={'class': 'form-select'}))
    competencia = forms.CharField(label='Competência (AAAA-MM)', max_length=7,
                                  widget=forms.TextInput(attrs={'type': 'month', 'class': 'form-control'}))

    def __init__(self, *args, clinica=None, **kw):
        super().__init__(*args, **kw)
        self.fields['operadora'].queryset = Operadora.objects.filter(clinica=clinica, ativo=True)


@acesso('convenios')
def lotes(request):
    form = NovoLoteForm(request.POST or None, clinica=request.clinica,
                        initial={'competencia': timezone.localdate().strftime('%Y-%m')})
    if request.method == 'POST' and tem_permissao(request, 'convenios', 'editar') and form.is_valid():
        op, comp = form.cleaned_data['operadora'], form.cleaned_data['competencia']
        ano, mes = map(int, comp.split('-'))
        abertas = GuiaTISS.objects.filter(clinica=request.clinica, operadora=op, status='aberta', lote__isnull=True,
                                          data_atendimento__year=ano, data_atendimento__month=mes)
        if not abertas.exists():
            messages.warning(request, f'Nenhuma guia aberta de {op} em {mes:02d}/{ano}.')
        else:
            with transaction.atomic():
                lote = LoteTISS.objects.create(clinica=request.clinica, operadora=op, competencia=comp,
                                               numero=proximo_lote(request.clinica))
                n = abertas.update(lote=lote, status='em_lote')
                lote.recalcular()
            messages.success(request, f'Lote {lote.numero} criado com {n} guia(s).')
            return redirect('convenios:lote', lote.pk)
    pendentes = GuiaTISS.objects.filter(clinica=request.clinica, status='aberta').values(
        'operadora__nome').annotate(n=Count('id'), v=Sum('valor_total'))
    return render(request, 'convenios/lotes.html', {
        'lotes': LoteTISS.objects.filter(clinica=request.clinica).select_related('operadora').annotate(n=Count('guias')),
        'form': form, 'pendentes': pendentes, 'pode_editar': tem_permissao(request, 'convenios', 'editar')})


@acesso('convenios')
def lote(request, pk):
    lote = get_object_or_404(LoteTISS.objects.select_related('operadora'), pk=pk, clinica=request.clinica)
    return render(request, 'convenios/lote.html', {
        'lote': lote, 'guias': lote.guias.select_related('paciente', 'medico'), 'erros': tiss.validar_lote(lote),
        'motivos': MOTIVOS_GLOSA, 'pode_editar': tem_permissao(request, 'convenios', 'editar')})


@acesso('convenios', 'editar')
@require_POST
def lote_acao(request, pk):
    from financeiro.models import Lancamento
    lote = get_object_or_404(LoteTISS.objects.select_related('operadora', 'clinica'), pk=pk, clinica=request.clinica)
    acao = request.POST.get('acao')
    if acao == 'xml':
        conteudo, h = tiss.gerar_xml(lote)
        nome = f'lote_{lote.numero}_{lote.operadora.registro_ans or "ans"}.xml'
        lote.xml.save(nome, ContentFile(conteudo), save=False)
        lote.hash_xml = h
        lote.save(update_fields=['xml', 'hash_xml', 'atualizado_em'])
        resp = FileResponse(lote.xml.open('rb'), content_type='application/xml', as_attachment=True, filename=nome)
        return resp
    if acao == 'enviar' and lote.status == 'aberto':
        with transaction.atomic():
            lote.status, lote.data_envio = 'enviado', timezone.localdate()
            lote.protocolo = request.POST.get('protocolo', '')[:60]
            lote.lancamento = Lancamento.objects.create(
                clinica=request.clinica, tipo='receita', descricao=f'Faturamento {lote}', valor=lote.valor_total,
                vencimento=lote.data_envio + timedelta(days=lote.operadora.prazo_pagamento_dias),
                categoria=Lancamento.categoria_padrao(request.clinica, 'receita', 'Convênios'),
                forma_pagamento='convenio', documento=f'Lote {lote.numero}', criado_por=request.user)
            lote.save()
            lote.guias.update(status='enviada')
        messages.success(request, 'Lote marcado como enviado. Conta a receber criada no financeiro.')
    elif acao == 'remover_guia' and lote.status == 'aberto':
        GuiaTISS.objects.filter(pk=request.POST.get('guia'), lote=lote).update(lote=None, status='aberta')
        lote.recalcular()
    elif acao == 'pagamento':
        with transaction.atomic():
            total_pago = Decimal('0')
            for g in lote.guias.all():
                from cadastros.importacao import decimal_br
                pago = decimal_br(request.POST.get(f'pago_{g.pk}'))
                if pago is None:
                    pago = g.valor_total
                g.valor_pago = min(max(pago, Decimal('0')), g.valor_total)
                g.glosa_codigo = request.POST.get(f'glosa_{g.pk}', '')[:4]
                g.glosa_motivo = request.POST.get(f'motivo_{g.pk}', '')[:250]
                g.save()
                g.status = 'paga' if g.valor_glosado == 0 else ('glosada' if g.valor_pago == 0 else 'glosa_parcial')
                g.save(update_fields=['status', 'atualizado_em'])
                total_pago += g.valor_pago
            lote.valor_pago = total_pago
            lote.data_pagamento = timezone.localdate()
            lote.status = 'pago' if total_pago >= lote.valor_total else 'pago_parcial'
            lote.save()
            if lote.lancamento_id:
                lan = lote.lancamento
                lan.status, lan.data_pagamento, lan.valor_pago = 'pago', lote.data_pagamento, total_pago
                lan.observacoes = (lan.observacoes + f'\nGlosa: {lote.valor_total - total_pago}').strip()
                lan.save()
        messages.success(request, f'Pagamento registrado: recebido {total_pago} · glosado {lote.valor_total - total_pago}.')
    return redirect('convenios:lote', lote.pk)


@acesso('convenios')
def glosas(request):
    qs = GuiaTISS.objects.filter(clinica=request.clinica, valor_glosado__gt=0).select_related('paciente', 'operadora', 'lote')
    por_op = qs.values('operadora__nome').annotate(n=Count('id'), v=Sum('valor_glosado')).order_by('-v')
    por_motivo = qs.values('glosa_codigo').annotate(n=Count('id'), v=Sum('valor_glosado')).order_by('-v')
    nomes = dict(MOTIVOS_GLOSA)
    return render(request, 'convenios/glosas.html', {
        'guias': qs[:300], 'por_op': por_op, 'por_motivo': [(nomes.get(m['glosa_codigo'], m['glosa_codigo'] or 'Não informado'),
                                                             m['n'], m['v']) for m in por_motivo]})
