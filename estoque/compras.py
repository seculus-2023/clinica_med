"""Fornecedores, pedidos de compra, inventário e lotes a vencer."""
from datetime import timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contas.crud import ClinicaModelForm, Crud, estilizar_campos
from contas.permissoes import acesso, tem_permissao

from .models import Fornecedor, Inventario, ItemInventario, ItemPedido, MovimentoEstoque, PedidoCompra, Produto


def lancar_despesa(clinica, descricao, valor, vencimento, fornecedor=None, documento='', usuario=None):
    from financeiro.models import Lancamento
    return Lancamento.objects.create(
        clinica=clinica, tipo='despesa', descricao=descricao, valor=valor, vencimento=vencimento,
        categoria=Lancamento.categoria_padrao(clinica, 'despesa', 'Compras de estoque'),
        fornecedor=str(fornecedor or '')[:150], documento=documento[:50], criado_por=usuario)


class FornecedorForm(ClinicaModelForm):
    class Meta:
        model = Fornecedor
        exclude = []


class FornecedorCrud(Crud):
    model, form_class = Fornecedor, FornecedorForm
    modulo = 'estoque'
    nome, nome_plural, url, icone = 'Fornecedor', 'Fornecedores', 'estoque:fornecedor', 'bi-truck'
    colunas = [('nome', 'Fornecedor'), ('cnpj', 'CNPJ'), ('contato', 'Contato'), ('telefone', 'Telefone'),
               ('prazo_pagamento_dias', 'Prazo (dias)'), ('ativo', 'Ativo')]
    busca = ['nome', 'cnpj', 'contato']


# ------------------------------------------------------------------ pedidos de compra
class PedidoForm(ClinicaModelForm):
    class Meta:
        model = PedidoCompra
        fields = ['fornecedor', 'data', 'previsao_entrega', 'nota_fiscal', 'observacoes']


class ItemPedidoForm(forms.ModelForm):
    class Meta:
        model = ItemPedido
        fields = ['produto', 'quantidade', 'custo_unitario', 'lote', 'validade']

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['produto'].queryset = Produto.objects.filter(clinica=clinica, ativo=True)
        estilizar_campos(self)


ItensPedido = forms.inlineformset_factory(PedidoCompra, ItemPedido, form=ItemPedidoForm, extra=3, can_delete=True)


@acesso('estoque')
def pedidos(request):
    qs = PedidoCompra.objects.filter(clinica=request.clinica).select_related('fornecedor').prefetch_related('itens')
    if request.GET.get('status'):
        qs = qs.filter(status=request.GET['status'])
    baixo = Produto.objects.filter(clinica=request.clinica, ativo=True, saldo__lte=F('estoque_minimo'))
    return render(request, 'estoque/pedidos.html', {'pedidos': qs[:200], 'status': PedidoCompra.STATUS,
                                                    'f': request.GET, 'baixo': baixo,
                                                    'pode_editar': tem_permissao(request, 'estoque', 'editar')})


@acesso('estoque', 'editar')
def pedido_form(request, pk=None):
    ped = get_object_or_404(PedidoCompra, pk=pk, clinica=request.clinica) if pk else None
    if ped and ped.status in ('recebido', 'cancelado'):
        messages.warning(request, 'Pedido recebido/cancelado não pode ser alterado.')
        return redirect('estoque:pedido', ped.pk)
    form = PedidoForm(request.POST or None, instance=ped, clinica=request.clinica)
    inicial = []
    if not ped and request.GET.get('reposicao'):
        for p in Produto.objects.filter(clinica=request.clinica, ativo=True, saldo__lte=F('estoque_minimo')):
            inicial.append({'produto': p.pk, 'quantidade': max(p.estoque_minimo * 2 - p.saldo, 1),
                            'custo_unitario': p.custo_medio})
    Fs = forms.inlineformset_factory(PedidoCompra, ItemPedido, form=ItemPedidoForm, can_delete=True,
                                     extra=max(3, len(inicial)))
    itens = Fs(request.POST or None, instance=ped or PedidoCompra(), form_kwargs={'clinica': request.clinica},
               initial=inicial or None)
    if request.method == 'POST' and form.is_valid() and itens.is_valid():
        with transaction.atomic():
            o = form.save(commit=False)
            if not o.pk:
                o.clinica, o.usuario = request.clinica, request.user
            o.save()
            itens.instance = o
            for it in itens.save(commit=False):
                it.save()
            for it in itens.deleted_objects:
                it.delete()
        messages.success(request, 'Pedido salvo.')
        return redirect('estoque:pedido', o.pk)
    return render(request, 'estoque/pedido_form.html', {'form': form, 'itens': itens, 'obj': ped})


@acesso('estoque')
def pedido(request, pk):
    ped = get_object_or_404(PedidoCompra.objects.select_related('fornecedor'), pk=pk, clinica=request.clinica)
    return render(request, 'estoque/pedido.html', {'p': ped, 'itens': ped.itens.select_related('produto'),
                                                   'hoje': timezone.localdate(),
                                                   'pode_editar': tem_permissao(request, 'estoque', 'editar')})


@acesso('estoque', 'editar')
@require_POST
def pedido_acao(request, pk):
    from cadastros.importacao import decimal_br
    ped = get_object_or_404(PedidoCompra.objects.select_related('fornecedor'), pk=pk, clinica=request.clinica)
    acao = request.POST.get('acao')
    if acao == 'enviar' and ped.status == 'rascunho':
        ped.status = 'enviado'
        ped.save(update_fields=['status', 'atualizado_em'])
        messages.success(request, 'Pedido marcado como enviado ao fornecedor.')
    elif acao == 'cancelar' and ped.status in ('rascunho', 'enviado'):
        ped.status = 'cancelado'
        ped.save(update_fields=['status', 'atualizado_em'])
    elif acao == 'receber' and ped.status in ('rascunho', 'enviado'):
        from django.utils.dateparse import parse_date
        with transaction.atomic():
            data = parse_date(request.POST.get('data', '')) or timezone.localdate()
            ped.nota_fiscal = request.POST.get('nota_fiscal', ped.nota_fiscal)[:50]
            total = Decimal('0')
            for it in ped.itens.select_related('produto'):
                qtd = decimal_br(request.POST.get(f'qtd_{it.pk}')) if request.POST.get(f'qtd_{it.pk}') else it.quantidade
                if not qtd or qtd <= 0:
                    continue
                custo = decimal_br(request.POST.get(f'custo_{it.pk}')) or it.custo_unitario
                it.quantidade, it.custo_unitario = qtd, custo
                it.lote = request.POST.get(f'lote_{it.pk}', it.lote)[:50]
                it.validade = parse_date(request.POST.get(f'validade_{it.pk}', '') or '') or it.validade
                it.save()
                MovimentoEstoque.objects.create(
                    clinica=request.clinica, produto=it.produto, tipo='entrada', quantidade=qtd, custo_unitario=custo,
                    data=data, lote=it.lote, validade=it.validade, fornecedor=ped.fornecedor.nome[:150],
                    fornecedor_cad=ped.fornecedor, nota_fiscal=ped.nota_fiscal, usuario=request.user,
                    motivo=f'Recebimento do pedido {ped.pk}')
                total += it.total
            if total and request.POST.get('gerar_despesa', '1') == '1':
                ped.lancamento = lancar_despesa(
                    request.clinica, f'Compra - pedido {ped.pk} - {ped.fornecedor}', total,
                    data + timedelta(days=ped.fornecedor.prazo_pagamento_dias), ped.fornecedor,
                    f'NF {ped.nota_fiscal}' if ped.nota_fiscal else f'Pedido {ped.pk}', request.user)
            ped.status, ped.recebido_em = 'recebido', data
            ped.save()
        messages.success(request, f'Pedido recebido: estoque atualizado' + (' e despesa lançada no contas a pagar.'
                                                                            if ped.lancamento_id else '.'))
    return redirect('estoque:pedido', ped.pk)


# ------------------------------------------------------------------ inventário
@acesso('estoque')
def inventarios(request):
    if request.method == 'POST' and tem_permissao(request, 'estoque', 'editar'):
        with transaction.atomic():
            inv = Inventario.objects.create(clinica=request.clinica, usuario=request.user,
                                            observacoes=request.POST.get('observacoes', ''))
            ItemInventario.objects.bulk_create([
                ItemInventario(inventario=inv, produto=p, saldo_sistema=p.saldo)
                for p in Produto.objects.filter(clinica=request.clinica, ativo=True).order_by('categoria', 'nome')])
        return redirect('estoque:inventario', inv.pk)
    return render(request, 'estoque/inventarios.html', {
        'inventarios': Inventario.objects.filter(clinica=request.clinica).select_related('usuario'),
        'pode_editar': tem_permissao(request, 'estoque', 'editar')})


@acesso('estoque')
def inventario(request, pk):
    from cadastros.importacao import decimal_br
    inv = get_object_or_404(Inventario, pk=pk, clinica=request.clinica)
    itens = list(inv.itens.select_related('produto').order_by('produto__categoria', 'produto__nome'))
    if request.method == 'POST' and inv.status == 'aberto' and tem_permissao(request, 'estoque', 'editar'):
        for it in itens:
            bruto = request.POST.get(f'c_{it.pk}', '').strip()
            it.contado = decimal_br(bruto) if bruto else None
            it.save(update_fields=['contado'])
        if request.POST.get('concluir'):
            with transaction.atomic():
                n = 0
                for it in itens:
                    dif = it.diferenca
                    if dif:
                        MovimentoEstoque.objects.create(
                            clinica=request.clinica, produto=it.produto, tipo='ajuste_mais' if dif > 0 else 'ajuste_menos',
                            quantidade=abs(dif), data=inv.data, usuario=request.user,
                            motivo=f'Ajuste de inventário {inv.data:%d/%m/%Y}')
                        n += 1
                inv.status = 'concluido'
                inv.save(update_fields=['status', 'atualizado_em'])
            messages.success(request, f'Inventário concluído: {n} ajuste(s) lançado(s) no estoque.')
        else:
            messages.success(request, 'Contagem salva.')
        return redirect('estoque:inventario', inv.pk)
    return render(request, 'estoque/inventario.html', {'inv': inv, 'itens': itens,
                                                       'pode_editar': tem_permissao(request, 'estoque', 'editar')})


# ------------------------------------------------------------------ lotes a vencer
def lotes_a_vencer(clinica, dias=60):
    hoje = timezone.localdate()
    qs = MovimentoEstoque.objects.filter(clinica=clinica, tipo='entrada', validade__isnull=False,
                                         validade__lte=hoje + timedelta(days=dias), produto__saldo__gt=0,
                                         produto__ativo=True).select_related('produto').order_by('validade')
    vistos, lista = set(), []
    for m in qs:
        chave = (m.produto_id, m.lote, m.validade)
        if chave in vistos:
            continue
        vistos.add(chave)
        m.dias = (m.validade - hoje).days
        m.dias_abs = abs(m.dias)
        lista.append(m)
    return lista


@acesso('estoque')
def lotes(request):
    dias = int(request.GET.get('dias') or 60)
    return render(request, 'estoque/lotes.html', {'lotes': lotes_a_vencer(request.clinica, dias), 'dias': dias})
