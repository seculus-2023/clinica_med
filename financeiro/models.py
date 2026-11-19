from datetime import date
from decimal import ROUND_DOWN, Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from cadastros.models import Medico, Paciente
from contas.models import ClinicaModel

FORMAS_PAGAMENTO = [('', '---------'), ('dinheiro', 'Dinheiro'), ('pix', 'PIX'), ('credito', 'Cartão de crédito'),
                    ('debito', 'Cartão de débito'), ('boleto', 'Boleto'), ('transferencia', 'Transferência'),
                    ('convenio', 'Convênio'), ('outro', 'Outro')]
TIPOS = [('receita', 'Receita (a receber)'), ('despesa', 'Despesa (a pagar)')]


def _somar_meses(d, n):
    m = d.month - 1 + n
    ano, mes = d.year + m // 12, m % 12 + 1
    import calendar
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


class CategoriaFinanceira(ClinicaModel):
    nome = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=TIPOS)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['tipo', 'nome']
        verbose_name = 'Categoria financeira'

    def __str__(self):
        return self.nome


class ContaBancaria(ClinicaModel):
    nome = models.CharField(max_length=100, help_text='Ex.: Itaú - conta movimento')
    banco = models.CharField(max_length=60, blank=True)
    agencia = models.CharField('Agência', max_length=20, blank=True)
    numero = models.CharField('Conta', max_length=30, blank=True)
    saldo_inicial = models.DecimalField('Saldo inicial (R$)', max_digits=12, decimal_places=2, default=0)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Conta bancária'

    def __str__(self):
        return self.nome


class Lancamento(ClinicaModel):
    STATUS = [('pendente', 'Pendente'), ('pago', 'Pago / recebido'), ('cancelado', 'Cancelado')]
    tipo = models.CharField(max_length=10, choices=TIPOS, default='receita')
    descricao = models.CharField('Descrição', max_length=200)
    categoria = models.ForeignKey(CategoriaFinanceira, on_delete=models.SET_NULL, null=True, blank=True)
    valor = models.DecimalField('Valor (R$)', max_digits=12, decimal_places=2)
    vencimento = models.DateField(default=timezone.localdate)
    status = models.CharField(max_length=10, choices=STATUS, default='pendente')
    data_pagamento = models.DateField('Data do pagamento', null=True, blank=True)
    valor_pago = models.DecimalField('Valor pago (R$)', max_digits=12, decimal_places=2, null=True, blank=True)
    forma_pagamento = models.CharField('Forma de pagamento', max_length=20, choices=FORMAS_PAGAMENTO, blank=True)
    parcela = models.CharField(max_length=10, blank=True, help_text='Ex.: 1/3')
    paciente = models.ForeignKey(Paciente, on_delete=models.SET_NULL, null=True, blank=True)
    medico = models.ForeignKey(Medico, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='Profissional')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False)
    pacote = models.ForeignKey('agenda.PacoteSessao', on_delete=models.SET_NULL, null=True, blank=True,
                               editable=False)
    conta = models.ForeignKey(ContaBancaria, on_delete=models.SET_NULL, null=True, blank=True,
                              verbose_name='Conta bancária')
    conciliado = models.BooleanField(default=False, editable=False)
    caixa = models.ForeignKey('Caixa', on_delete=models.SET_NULL, null=True, blank=True, related_name='movimentos',
                              editable=False)
    orcamento = models.ForeignKey('Orcamento', on_delete=models.SET_NULL, null=True, blank=True, related_name='lancamentos',
                                  editable=False)
    fornecedor = models.CharField('Fornecedor / favorecido', max_length=150, blank=True)
    documento = models.CharField('Nº documento', max_length=50, blank=True)
    observacoes = models.TextField('Observações', blank=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)

    class Meta:
        ordering = ['vencimento', 'id']
        verbose_name = 'Lançamento financeiro'

    def __str__(self):
        return self.descricao

    def save(self, *args, **kwargs):
        if self.status == 'pago':
            self.data_pagamento = self.data_pagamento or timezone.localdate()
            if self.valor_pago is None:
                self.valor_pago = self.valor
        super().save(*args, **kwargs)

    @property
    def atrasado(self):
        return self.status == 'pendente' and self.vencimento < timezone.localdate()

    @property
    def situacao(self):
        return 'Atrasado' if self.atrasado else self.get_status_display()

    @staticmethod
    def categoria_padrao(clinica, tipo, nome):
        cat, _ = CategoriaFinanceira.objects.get_or_create(clinica=clinica, tipo=tipo, nome=nome)
        return cat

    @classmethod
    def gerar_parcelas(cls, clinica, descricao, total, parcelas, primeiro_vencimento, primeira_paga=False,
                       forma='', paciente=None, pacote=None, usuario=None, tipo='receita', categoria='Pacotes',
                       medico=None):
        total = Decimal(total)
        base = (total / parcelas).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
        cat = cls.categoria_padrao(clinica, tipo, categoria)
        criados = []
        for i in range(parcelas):
            valor = base if i < parcelas - 1 else total - base * (parcelas - 1)
            pago = primeira_paga and i == 0
            criados.append(cls.objects.create(
                clinica=clinica, tipo=tipo, descricao=descricao, categoria=cat, valor=valor,
                vencimento=_somar_meses(primeiro_vencimento, i), status='pago' if pago else 'pendente',
                forma_pagamento=forma, parcela=f'{i + 1}/{parcelas}' if parcelas > 1 else '',
                paciente=paciente, pacote=pacote, medico=medico, criado_por=usuario))
        return criados


class TransacaoBancaria(ClinicaModel):
    """Linha do extrato bancário importado (OFX/CSV) para conciliação."""
    conta = models.ForeignKey(ContaBancaria, on_delete=models.CASCADE, related_name='transacoes')
    data = models.DateField()
    valor = models.DecimalField(max_digits=12, decimal_places=2, help_text='Positivo = crédito; negativo = débito')
    descricao = models.CharField(max_length=250, blank=True)
    fitid = models.CharField('ID da transação', max_length=120)
    lancamento = models.ForeignKey(Lancamento, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='transacoes')
    ignorada = models.BooleanField(default=False)

    class Meta:
        ordering = ['-data', '-id']
        unique_together = ('conta', 'fitid')
        verbose_name = 'Transação bancária'

    def __str__(self):
        return f'{self.data:%d/%m/%Y} {self.valor} {self.descricao}'

    @property
    def conciliada(self):
        return self.lancamento_id is not None


class Caixa(ClinicaModel):
    """Caixa diário por usuário: abertura, movimentos (baixas feitas com o caixa aberto) e fechamento."""
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='caixas')
    aberto_em = models.DateTimeField(default=timezone.now)
    valor_abertura = models.DecimalField('Troco inicial (R$)', max_digits=12, decimal_places=2, default=0)
    fechado_em = models.DateTimeField(null=True, blank=True)
    valor_informado = models.DecimalField('Dinheiro contado no fechamento (R$)', max_digits=12, decimal_places=2,
                                          null=True, blank=True)
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        ordering = ['-aberto_em']

    def __str__(self):
        return f'Caixa {self.usuario} {timezone.localtime(self.aberto_em):%d/%m/%Y %H:%M}'

    @property
    def aberto(self):
        return self.fechado_em is None

    def resumo(self):
        movs = self.movimentos.filter(status='pago')
        formas = dict(FORMAS_PAGAMENTO)
        por_forma = {}
        for lan in movs:
            sinal = 1 if lan.tipo == 'receita' else -1
            chave = lan.forma_pagamento or 'outro'
            por_forma[chave] = por_forma.get(chave, Decimal('0')) + sinal * (lan.valor_pago or lan.valor)
        dinheiro = por_forma.get('dinheiro', Decimal('0'))
        esperado = self.valor_abertura + dinheiro
        return {'por_forma': [(formas.get(k) or 'Outro', v) for k, v in sorted(por_forma.items())],
                'total': sum(por_forma.values(), Decimal('0')), 'dinheiro_esperado': esperado,
                'diferenca': (self.valor_informado - esperado) if self.valor_informado is not None else None,
                'qtd': movs.count()}

    @classmethod
    def aberto_do_usuario(cls, clinica, usuario):
        return cls.objects.filter(clinica=clinica, usuario=usuario, fechado_em__isnull=True).first()


class Orcamento(ClinicaModel):
    STATUS = [('aberto', 'Em aberto'), ('aprovado', 'Aprovado'), ('recusado', 'Recusado'), ('expirado', 'Expirado')]
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='orcamentos')
    medico = models.ForeignKey(Medico, on_delete=models.SET_NULL, null=True, blank=True, verbose_name='Profissional')
    data = models.DateField(default=timezone.localdate)
    validade = models.DateField('Válido até', null=True, blank=True)
    desconto = models.DecimalField('Desconto (R$)', max_digits=12, decimal_places=2, default=0)
    parcelas = models.PositiveIntegerField('Parcelas sugeridas', default=1)
    observacoes = models.TextField('Observações / condições', blank=True)
    status = models.CharField(max_length=10, choices=STATUS, default='aberto')
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+',
                                   editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Orçamento'

    def __str__(self):
        return f'Orçamento {self.pk} - {self.paciente}'

    @property
    def subtotal(self):
        return sum((i.total for i in self.itens.all()), Decimal('0'))

    @property
    def total(self):
        return max(self.subtotal - (self.desconto or 0), Decimal('0'))


class ItemOrcamento(models.Model):
    orcamento = models.ForeignKey(Orcamento, on_delete=models.CASCADE, related_name='itens')
    tipo = models.ForeignKey('cadastros.TipoAtendimento', on_delete=models.SET_NULL, null=True, blank=True,
                             verbose_name='Atendimento / procedimento')
    descricao = models.CharField('Descrição', max_length=200, blank=True)
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField('Valor unitário (R$)', max_digits=12, decimal_places=2, default=0)

    @property
    def total(self):
        return (self.valor_unitario or 0) * (self.quantidade or 0)

    @property
    def nome(self):
        return self.descricao or (str(self.tipo) if self.tipo else '')
