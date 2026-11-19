"""Venda do sistema para outras clínicas (SaaS): planos, assinaturas e faturas."""
import calendar
from datetime import date, timedelta
from decimal import Decimal

from django.db import models
from django.utils import timezone

from contas.models import Clinica


class PlanoSaaS(models.Model):
    nome = models.CharField(max_length=80)
    descricao = models.TextField('Descrição / recursos', blank=True)
    preco_mensal = models.DecimalField('Preço mensal (R$)', max_digits=10, decimal_places=2)
    max_usuarios = models.PositiveIntegerField('Máximo de usuários', default=5, help_text='0 = ilimitado')
    max_medicos = models.PositiveIntegerField('Máximo de profissionais', default=2, help_text='0 = ilimitado')
    dias_teste = models.PositiveIntegerField('Dias de teste grátis', default=14)
    publico = models.BooleanField('Aparece no cadastro público', default=True)
    ativo = models.BooleanField(default=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['ordem', 'preco_mensal']
        verbose_name = 'Plano (SaaS)'
        verbose_name_plural = 'Planos (SaaS)'

    def __str__(self):
        return f'{self.nome} (R$ {self.preco_mensal}/mês)'


class Assinatura(models.Model):
    STATUS = [('teste', 'Período de teste'), ('ativa', 'Ativa'), ('inadimplente', 'Inadimplente'),
              ('suspensa', 'Suspensa'), ('cancelada', 'Cancelada')]
    clinica = models.OneToOneField(Clinica, on_delete=models.CASCADE, related_name='assinatura')
    plano = models.ForeignKey(PlanoSaaS, on_delete=models.PROTECT, related_name='assinaturas')
    status = models.CharField(max_length=15, choices=STATUS, default='teste')
    teste_ate = models.DateField('Teste até', null=True, blank=True)
    dia_vencimento = models.PositiveSmallIntegerField('Dia de vencimento', default=10)
    responsavel_email = models.EmailField('E-mail de cobrança', blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    observacoes = models.TextField(blank=True)

    class Meta:
        verbose_name = 'Assinatura da clínica'

    def __str__(self):
        return f'{self.clinica} - {self.plano.nome} ({self.get_status_display()})'

    @property
    def bloqueada(self):
        """Clínica sem acesso: cancelada, suspensa, teste vencido ou inadimplente há mais de 7 dias."""
        hoje = timezone.localdate()
        if self.status in ('cancelada', 'suspensa'):
            return True
        if self.status == 'teste' and self.teste_ate and self.teste_ate < hoje:
            return not self.faturas.filter(status='paga').exists()
        if self.status == 'inadimplente':
            atrasada = self.faturas.filter(status='pendente', vencimento__lt=hoje - timedelta(days=7)).exists()
            return atrasada
        return False

    def vencimento_em(self, ano, mes):
        dia = min(self.dia_vencimento, calendar.monthrange(ano, mes)[1])
        return date(ano, mes, dia)

    def limite_atingido(self, tipo):
        lim = self.plano.max_usuarios if tipo == 'usuarios' else self.plano.max_medicos
        if not lim:
            return False
        if tipo == 'usuarios':
            atual = self.clinica.vinculos.filter(ativo=True, usuario__is_superuser=False).count()
        else:
            from cadastros.models import Medico
            atual = Medico.objects.filter(clinica=self.clinica, ativo=True).count()
        return atual >= lim


class Fatura(models.Model):
    STATUS = [('pendente', 'Pendente'), ('paga', 'Paga'), ('cancelada', 'Cancelada')]
    assinatura = models.ForeignKey(Assinatura, on_delete=models.CASCADE, related_name='faturas')
    competencia = models.CharField(max_length=7, help_text='AAAA-MM')
    valor = models.DecimalField(max_digits=10, decimal_places=2)
    vencimento = models.DateField()
    status = models.CharField(max_length=10, choices=STATUS, default='pendente')
    pago_em = models.DateField(null=True, blank=True)
    forma = models.CharField(max_length=30, blank=True)
    txid = models.CharField('Identificador PIX', max_length=25, blank=True)
    observacoes = models.CharField(max_length=200, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-vencimento']
        unique_together = ('assinatura', 'competencia')

    def __str__(self):
        return f'Fatura {self.competencia} - {self.assinatura.clinica}'

    @property
    def atrasada(self):
        return self.status == 'pendente' and self.vencimento < timezone.localdate()

    def save(self, *args, **kwargs):
        if not self.txid:
            import secrets
            self.txid = ('MA' + secrets.token_hex(8)).upper()[:25]
        super().save(*args, **kwargs)

    @property
    def valor_decimal(self):
        return Decimal(self.valor)
