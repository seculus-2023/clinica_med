from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.db.models import Sum
from django.utils import timezone

from cadastros.models import Medicamento, Paciente
from contas.models import ClinicaModel


class Produto(ClinicaModel):
    CATEGORIAS = [('medicamento', 'Medicamento'), ('material', 'Material médico'), ('insumo', 'Insumo'),
                  ('limpeza', 'Limpeza / higiene'), ('escritorio', 'Escritório'), ('outro', 'Outro')]
    nome = models.CharField(max_length=150)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, default='material')
    medicamento = models.ForeignKey(Medicamento, on_delete=models.SET_NULL, null=True, blank=True,
                                    verbose_name='Medicamento vinculado')
    unidade = models.CharField(max_length=20, default='un', help_text='un, cx, ml, fr, pct...')
    codigo = models.CharField('Código / EAN', max_length=50, blank=True)
    estoque_minimo = models.DecimalField('Estoque mínimo', max_digits=12, decimal_places=2, default=0)
    custo_medio = models.DecimalField('Custo médio (R$)', max_digits=12, decimal_places=2, default=0,
                                      editable=False)
    saldo = models.DecimalField(max_digits=12, decimal_places=2, default=0, editable=False)
    localizacao = models.CharField('Localização', max_length=80, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} ({self.unidade})'

    @property
    def abaixo_minimo(self):
        return self.saldo <= self.estoque_minimo

    @property
    def valor_estoque(self):
        return (self.saldo or 0) * (self.custo_medio or 0)

    def recalcular(self):
        movs = self.movimentos.all()
        entradas = movs.filter(tipo__in=MovimentoEstoque.ENTRADAS).aggregate(s=Sum('quantidade'))['s'] or 0
        saidas = movs.exclude(tipo__in=MovimentoEstoque.ENTRADAS).aggregate(s=Sum('quantidade'))['s'] or 0
        self.saldo = Decimal(entradas) - Decimal(saidas)
        compras = movs.filter(tipo='entrada', custo_unitario__gt=0)
        qtd = compras.aggregate(s=Sum('quantidade'))['s'] or 0
        if qtd:
            total = sum((m.quantidade * m.custo_unitario for m in compras), Decimal('0'))
            self.custo_medio = (total / qtd).quantize(Decimal('0.01'))
        self.save(update_fields=['saldo', 'custo_medio', 'atualizado_em'])

    def lotes_vencendo(self, dias=60):
        limite = timezone.localdate() + timedelta(days=dias)
        return self.movimentos.filter(tipo='entrada', validade__isnull=False, validade__lte=limite)


class InsumoAtendimento(ClinicaModel):
    """Insumos consumidos por tipo de atendimento/procedimento (baixa automática ao concluir)."""
    tipo = models.ForeignKey('cadastros.TipoAtendimento', on_delete=models.CASCADE, related_name='insumos',
                             verbose_name='Tipo de atendimento')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='usos')
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=1)

    class Meta:
        verbose_name = 'Insumo por atendimento'
        verbose_name_plural = 'Insumos por atendimento'

    def __str__(self):
        return f'{self.tipo}: {self.quantidade} {self.produto}'


class MovimentoEstoque(ClinicaModel):
    TIPOS = [('entrada', 'Entrada (compra)'), ('ajuste_mais', 'Ajuste (+)'), ('saida', 'Saída / consumo'),
             ('perda', 'Perda / vencimento'), ('ajuste_menos', 'Ajuste (-)')]
    ENTRADAS = ('entrada', 'ajuste_mais')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT, related_name='movimentos')
    tipo = models.CharField(max_length=15, choices=TIPOS, default='entrada')
    quantidade = models.DecimalField(max_digits=12, decimal_places=2)
    custo_unitario = models.DecimalField('Custo unitário (R$)', max_digits=12, decimal_places=2, default=0)
    data = models.DateField(default=timezone.localdate)
    lote = models.CharField(max_length=50, blank=True)
    validade = models.DateField(null=True, blank=True)
    fornecedor = models.CharField('Fornecedor (texto)', max_length=150, blank=True)
    fornecedor_cad = models.ForeignKey('Fornecedor', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='movimentos', verbose_name='Fornecedor')
    lancamento = models.ForeignKey('financeiro.Lancamento', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)
    nota_fiscal = models.CharField('Nota fiscal', max_length=50, blank=True)
    paciente = models.ForeignKey(Paciente, on_delete=models.SET_NULL, null=True, blank=True,
                                 help_text='Opcional: paciente que consumiu o item.')
    motivo = models.CharField('Observação / motivo', max_length=250, blank=True)
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='movimentos_estoque', editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+', editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Movimento de estoque'

    def __str__(self):
        return f'{self.get_tipo_display()} {self.quantidade} {self.produto}'

    @property
    def sinal(self):
        return 1 if self.tipo in self.ENTRADAS else -1

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._produto_original = self.produto_id

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.produto.recalcular()
        if self._produto_original and self._produto_original != self.produto_id:
            Produto.objects.get(pk=self._produto_original).recalcular()
        self._produto_original = self.produto_id

    def delete(self, *args, **kwargs):
        produto = self.produto
        r = super().delete(*args, **kwargs)
        produto.recalcular()
        return r


class Fornecedor(ClinicaModel):
    nome = models.CharField(max_length=150)
    cnpj = models.CharField('CNPJ / CPF', max_length=20, blank=True)
    contato = models.CharField(max_length=100, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    prazo_pagamento_dias = models.PositiveIntegerField('Prazo de pagamento (dias)', default=30)
    observacoes = models.TextField('Observações', blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Fornecedor'

    def __str__(self):
        return self.nome


class PedidoCompra(ClinicaModel):
    STATUS = [('rascunho', 'Rascunho'), ('enviado', 'Enviado ao fornecedor'), ('recebido', 'Recebido'),
              ('cancelado', 'Cancelado')]
    fornecedor = models.ForeignKey(Fornecedor, on_delete=models.PROTECT, related_name='pedidos')
    data = models.DateField(default=timezone.localdate)
    previsao_entrega = models.DateField('Previsão de entrega', null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='rascunho', editable=False)
    nota_fiscal = models.CharField('Nota fiscal', max_length=50, blank=True)
    observacoes = models.TextField('Observações', blank=True)
    recebido_em = models.DateField(null=True, blank=True, editable=False)
    lancamento = models.ForeignKey('financeiro.Lancamento', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+', editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Pedido de compra'

    def __str__(self):
        return f'Pedido {self.pk} - {self.fornecedor}'

    @property
    def total(self):
        return sum((i.total for i in self.itens.all()), Decimal('0'))


class ItemPedido(models.Model):
    pedido = models.ForeignKey(PedidoCompra, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.PROTECT)
    quantidade = models.DecimalField(max_digits=12, decimal_places=2, default=1)
    custo_unitario = models.DecimalField('Custo unitário (R$)', max_digits=12, decimal_places=2, default=0)
    lote = models.CharField(max_length=50, blank=True)
    validade = models.DateField(null=True, blank=True)

    @property
    def total(self):
        return (self.quantidade or 0) * (self.custo_unitario or 0)


class Inventario(ClinicaModel):
    """Contagem física do estoque; ao concluir, gera os ajustes (+/-) das diferenças."""
    STATUS = [('aberto', 'Em contagem'), ('concluido', 'Concluído')]
    data = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS, default='aberto', editable=False)
    observacoes = models.TextField('Observações', blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
                                editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Inventário'

    def __str__(self):
        return f'Inventário {self.data:%d/%m/%Y}'


class ItemInventario(models.Model):
    inventario = models.ForeignKey(Inventario, on_delete=models.CASCADE, related_name='itens')
    produto = models.ForeignKey(Produto, on_delete=models.CASCADE)
    saldo_sistema = models.DecimalField(max_digits=12, decimal_places=2)
    contado = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    @property
    def diferenca(self):
        return None if self.contado is None else self.contado - self.saldo_sistema
