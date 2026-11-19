from django import forms
from django.db.models import F
from django.shortcuts import get_object_or_404, render

from cadastros.models import Medicamento
from contas.crud import Autocomplete, ClinicaModelForm, Crud
from contas.permissoes import acesso

from .models import InsumoAtendimento, MovimentoEstoque, Produto


class ProdutoForm(ClinicaModelForm):
    class Meta:
        model = Produto
        exclude = []
        widgets = {'medicamento': Autocomplete('cadastros:api_medicamentos', Medicamento)}


class MovimentoForm(ClinicaModelForm):
    class Meta:
        model = MovimentoEstoque
        exclude = []

    def clean(self):
        d = super().clean()
        prod, qtd, tipo = d.get('produto'), d.get('quantidade'), d.get('tipo')
        if qtd is not None and qtd <= 0:
            self.add_error('quantidade', 'Informe uma quantidade maior que zero.')
        elif prod and qtd and tipo and tipo not in MovimentoEstoque.ENTRADAS:
            saldo = prod.saldo
            if self.instance.pk and self.instance.produto_id == prod.pk:
                saldo += self.instance.quantidade * -self.instance.sinal
            if qtd > saldo:
                self.add_error('quantidade', f'Saldo insuficiente. Disponível: {saldo} {prod.unidade}.')
        return d


class ProdutoCrud(Crud):
    model, form_class = Produto, ProdutoForm
    modulo = 'estoque'
    nome, nome_plural, url, icone = 'Produto', 'Produtos em estoque', 'estoque:produto', 'bi-box-seam'
    colunas = [('nome', 'Produto'), ('categoria', 'Categoria'), ('saldo', 'Saldo'), ('unidade', 'Un.'),
               ('estoque_minimo', 'Mínimo'), ('custo_medio', 'Custo médio', 'moeda'),
               ('valor_estoque', 'Valor em estoque', 'moeda')]
    busca = ['nome', 'codigo']
    filtros = [('categoria', 'Categoria', Produto.CATEGORIAS)]
    acoes_linha = [('estoque:produto_kardex', 'bi-clock-history', 'Movimentações')]

    @classmethod
    def queryset(cls, request):
        qs = Produto.objects.filter(clinica=request.clinica)
        if request.GET.get('baixo') == '1':
            qs = qs.filter(saldo__lte=F('estoque_minimo'))
        return qs


class MovimentoCrud(Crud):
    model, form_class = MovimentoEstoque, MovimentoForm
    modulo = 'estoque'
    nome, nome_plural, url, icone = 'Movimentação', 'Movimentações de estoque', 'estoque:movimento', \
        'bi-arrow-left-right'
    colunas = [('data', 'Data'), ('produto', 'Produto'), ('tipo', 'Tipo'), ('quantidade', 'Qtd.'),
               ('custo_unitario', 'Custo unit.', 'moeda'), ('lote', 'Lote'), ('validade', 'Validade'),
               ('usuario', 'Usuário')]
    busca = ['produto__nome', 'lote', 'fornecedor', 'nota_fiscal']
    filtros = [('tipo', 'Tipo', MovimentoEstoque.TIPOS)]

    @classmethod
    def antes_salvar(cls, request, obj, form):
        obj.usuario = obj.usuario or request.user

    @classmethod
    def queryset(cls, request):
        return MovimentoEstoque.objects.filter(clinica=request.clinica).select_related('produto', 'usuario')


@acesso('estoque')
def kardex(request, pk):
    prod = get_object_or_404(Produto, pk=pk, clinica=request.clinica)
    movs = list(prod.movimentos.select_related('usuario', 'paciente').order_by('data', 'id'))
    saldo = 0
    linhas = []
    for m in movs:
        saldo += m.quantidade * m.sinal
        linhas.append((m, saldo))
    linhas.reverse()
    return render(request, 'estoque/kardex.html', {'p': prod, 'linhas': linhas})


class InsumoForm(ClinicaModelForm):
    class Meta:
        model = InsumoAtendimento
        exclude = []


class InsumoCrud(Crud):
    model, form_class = InsumoAtendimento, InsumoForm
    modulo = 'estoque'
    nome, nome_plural, url, icone = 'Insumo', 'Insumos por atendimento', 'estoque:insumo', 'bi-diagram-2'
    descricao = 'Ao concluir o atendimento, estes insumos são baixados do estoque automaticamente (com lote e paciente).'
    colunas = [('tipo', 'Tipo de atendimento'), ('produto', 'Produto'), ('quantidade', 'Quantidade')]
    busca = ['tipo__nome', 'produto__nome']

    @classmethod
    def queryset(cls, request):
        return InsumoAtendimento.objects.filter(clinica=request.clinica).select_related('tipo', 'produto')
