"""Convênios (operadoras de saúde), tabela de preço por convênio e faturamento TISS."""
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from clinica.armazenamento import privado
from contas.models import ClinicaModel


class Operadora(ClinicaModel):
    nome = models.CharField('Operadora / convênio', max_length=150)
    registro_ans = models.CharField('Registro ANS', max_length=6, blank=True, help_text='6 dígitos')
    cnpj = models.CharField('CNPJ', max_length=20, blank=True)
    codigo_prestador = models.CharField('Código do prestador na operadora', max_length=20, blank=True,
                                        help_text='Código da clínica junto à operadora (usado no XML TISS).')
    versao_tiss = models.CharField('Versão TISS', max_length=10, default='4.01.00')
    prazo_pagamento_dias = models.PositiveIntegerField('Prazo de pagamento (dias)', default=30)
    exige_autorizacao = models.BooleanField('Exige autorização prévia para todos os procedimentos', default=False)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    portal = models.URLField('Portal do prestador', blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Operadora / convênio'
        verbose_name_plural = 'Operadoras / convênios'

    def __str__(self):
        return self.nome


class Plano(ClinicaModel):
    operadora = models.ForeignKey(Operadora, on_delete=models.CASCADE, related_name='planos')
    nome = models.CharField(max_length=120)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['operadora__nome', 'nome']

    def __str__(self):
        return f'{self.operadora} - {self.nome}'


class PrecoConvenio(ClinicaModel):
    """Tabela de preço por convênio (e opcionalmente por plano)."""
    operadora = models.ForeignKey(Operadora, on_delete=models.CASCADE, related_name='precos')
    plano = models.ForeignKey(Plano, on_delete=models.CASCADE, null=True, blank=True,
                              help_text='Vazio = vale para todos os planos da operadora.')
    tipo = models.ForeignKey('cadastros.TipoAtendimento', on_delete=models.CASCADE, related_name='precos_convenio',
                             verbose_name='Tipo de atendimento')
    codigo_tuss = models.CharField('Código TUSS', max_length=10, blank=True,
                                   help_text='Vazio = usa o código do procedimento vinculado ao tipo.')
    valor = models.DecimalField('Valor (R$)', max_digits=10, decimal_places=2)
    requer_autorizacao = models.BooleanField('Requer autorização prévia', default=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['operadora__nome', 'tipo__nome']
        unique_together = ('operadora', 'plano', 'tipo')
        verbose_name = 'Preço por convênio'
        verbose_name_plural = 'Tabela de preços por convênio'

    def __str__(self):
        return f'{self.operadora} / {self.tipo}: {self.valor}'

    @classmethod
    def buscar(cls, operadora, plano, tipo):
        if not operadora or not tipo:
            return None
        qs = cls.objects.filter(operadora=operadora, tipo=tipo, ativo=True)
        return (qs.filter(plano=plano).first() if plano else None) or qs.filter(plano__isnull=True).first()

    @property
    def codigo(self):
        return self.codigo_tuss or codigo_tuss_do_tipo(self.tipo)


def codigo_tuss_do_tipo(tipo):
    """Código TUSS do tipo de atendimento (códigos SUS/SIGTAP não valem para convênios/TISS)."""
    p = tipo.procedimento if tipo.procedimento_id else None
    return p.codigo if p and p.origem != 'sus' else ''


class LoteTISS(ClinicaModel):
    STATUS = [('aberto', 'Aberto'), ('enviado', 'Enviado'), ('pago_parcial', 'Pago com glosa'), ('pago', 'Pago'),
              ('cancelado', 'Cancelado')]
    operadora = models.ForeignKey(Operadora, on_delete=models.PROTECT, related_name='lotes')
    numero = models.PositiveIntegerField('Número do lote')
    competencia = models.CharField('Competência (AAAA-MM)', max_length=7)
    status = models.CharField(max_length=15, choices=STATUS, default='aberto')
    data_envio = models.DateField(null=True, blank=True)
    protocolo = models.CharField('Protocolo da operadora', max_length=60, blank=True)
    xml = models.FileField(upload_to='tiss/', storage=privado, blank=True)
    hash_xml = models.CharField(max_length=32, blank=True)
    valor_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    valor_pago = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    data_pagamento = models.DateField(null=True, blank=True)
    lancamento = models.ForeignKey('financeiro.Lancamento', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')

    class Meta:
        ordering = ['-numero']
        unique_together = ('clinica', 'numero')
        verbose_name = 'Lote TISS'

    def __str__(self):
        return f'Lote {self.numero} - {self.operadora} ({self.competencia})'

    @property
    def valor_glosado(self):
        return self.guias.aggregate(s=models.Sum('valor_glosado'))['s'] or Decimal('0')

    def recalcular(self):
        self.valor_total = self.guias.aggregate(s=models.Sum('valor_total'))['s'] or 0
        self.save(update_fields=['valor_total', 'atualizado_em'])


class GuiaTISS(ClinicaModel):
    TIPOS = [('consulta', 'Guia de consulta'), ('sp_sadt', 'Guia SP/SADT')]
    STATUS = [('aberta', 'Aberta (a faturar)'), ('em_lote', 'Em lote'), ('enviada', 'Enviada'),
              ('paga', 'Paga'), ('glosa_parcial', 'Glosa parcial'), ('glosada', 'Glosada'), ('cancelada', 'Cancelada')]
    TIPO_CONSULTA = [('1', 'Primeira consulta'), ('2', 'Retorno'), ('3', 'Pré-natal'), ('4', 'Por encaminhamento')]
    CARATER = [('1', 'Eletivo'), ('2', 'Urgência/emergência')]
    tipo = models.CharField(max_length=10, choices=TIPOS, default='consulta')
    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='guia', editable=False)
    paciente = models.ForeignKey('cadastros.Paciente', on_delete=models.PROTECT, related_name='guias')
    medico = models.ForeignKey('cadastros.Medico', on_delete=models.PROTECT, related_name='guias',
                               verbose_name='Profissional executante')
    operadora = models.ForeignKey(Operadora, on_delete=models.PROTECT, related_name='guias')
    plano = models.ForeignKey(Plano, on_delete=models.SET_NULL, null=True, blank=True)
    lote = models.ForeignKey(LoteTISS, on_delete=models.SET_NULL, null=True, blank=True, related_name='guias',
                             editable=False)
    numero_guia = models.CharField('Nº da guia no prestador', max_length=20)
    numero_guia_operadora = models.CharField('Nº da guia na operadora', max_length=20, blank=True)
    senha = models.CharField('Senha de autorização', max_length=20, blank=True)
    data_autorizacao = models.DateField(null=True, blank=True)
    carteirinha = models.CharField('Número da carteira', max_length=30)
    data_atendimento = models.DateField(default=timezone.localdate)
    tipo_consulta = models.CharField(max_length=1, choices=TIPO_CONSULTA, default='1')
    carater = models.CharField('Caráter do atendimento', max_length=1, choices=CARATER, default='1')
    indicacao_clinica = models.CharField('Indicação clínica', max_length=500, blank=True)
    cid = models.CharField('CID', max_length=10, blank=True)
    codigo_tabela = models.CharField('Tabela', max_length=2, default='22', help_text='22 = TUSS procedimentos')
    codigo_procedimento = models.CharField('Código do procedimento', max_length=10)
    descricao_procedimento = models.CharField('Descrição', max_length=150)
    quantidade = models.PositiveIntegerField(default=1)
    valor_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    valor_total = models.DecimalField(max_digits=10, decimal_places=2, editable=False)
    status = models.CharField(max_length=15, choices=STATUS, default='aberta')
    valor_pago = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    valor_glosado = models.DecimalField(max_digits=10, decimal_places=2, default=0, editable=False)
    glosa_codigo = models.CharField('Código da glosa (tabela 38)', max_length=4, blank=True)
    glosa_motivo = models.CharField('Motivo da glosa', max_length=250, blank=True)
    recurso = models.TextField('Recurso de glosa', blank=True)
    recurso_status = models.CharField(max_length=12, blank=True,
                                      choices=[('', '-'), ('enviado', 'Recurso enviado'), ('aceito', 'Aceito'),
                                               ('negado', 'Negado')])

    class Meta:
        ordering = ['-data_atendimento', '-id']
        verbose_name = 'Guia TISS'
        verbose_name_plural = 'Guias TISS'

    def __str__(self):
        return f'Guia {self.numero_guia} - {self.paciente}'

    def save(self, *args, **kwargs):
        self.valor_total = (self.valor_unitario or 0) * (self.quantidade or 1)
        if self.valor_pago is not None:
            self.valor_glosado = max(self.valor_total - self.valor_pago, Decimal('0'))
        super().save(*args, **kwargs)

    @staticmethod
    def proximo_numero(clinica):
        ultimo = GuiaTISS.objects.filter(clinica=clinica).order_by('-id').values_list('numero_guia', flat=True).first()
        try:
            return str(int(ultimo) + 1)
        except (TypeError, ValueError):
            return '1'
