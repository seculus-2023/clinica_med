import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.models import ClinicaModel

STATUS_CONSOME = ('aguardando', 'em_atendimento', 'concluido')
STATUS_RESERVA = ('agendado', 'confirmado')


class PacoteSessao(ClinicaModel):
    STATUS = [('ativo', 'Ativo'), ('concluido', 'Concluído'), ('cancelado', 'Cancelado')]
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='pacotes')
    tipo = models.ForeignKey(TipoAtendimento, on_delete=models.PROTECT, verbose_name='Tipo de atendimento')
    medico = models.ForeignKey(Medico, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='Profissional preferencial')
    quantidade = models.PositiveIntegerField('Quantidade de sessões', default=10)
    valor_total = models.DecimalField('Valor total (R$)', max_digits=10, decimal_places=2, default=0)
    data_compra = models.DateField('Data da compra', default=timezone.localdate)
    validade = models.DateField('Válido até', null=True, blank=True)
    faltas_consomem = models.BooleanField('Faltas consomem sessão', default=False)
    status = models.CharField(max_length=12, choices=STATUS, default='ativo')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        ordering = ['-data_compra', '-id']
        verbose_name = 'Pacote de sessões'

    def __str__(self):
        return f'{self.paciente} - {self.tipo} ({self.usadas}/{self.quantidade})'

    def _status_consumo(self):
        return STATUS_CONSOME + (('faltou',) if self.faltas_consomem else ())

    @property
    def usadas(self):
        return self.agendamentos.filter(status__in=self._status_consumo()).count()

    @property
    def agendadas(self):
        return self.agendamentos.filter(status__in=STATUS_RESERVA).count()

    @property
    def restantes(self):
        return max(self.quantidade - self.usadas, 0)

    @property
    def disponiveis(self):
        """Sessões ainda não usadas nem reservadas em agenda."""
        return max(self.quantidade - self.usadas - self.agendadas, 0)

    @property
    def percentual(self):
        return int(self.usadas * 100 / self.quantidade) if self.quantidade else 0

    @property
    def vencido(self):
        return bool(self.validade and self.validade < timezone.localdate())

    def atualizar_status(self):
        if self.status == 'ativo' and self.usadas >= self.quantidade:
            self.status = 'concluido'
            self.save(update_fields=['status', 'atualizado_em'])
        elif self.status == 'concluido' and self.usadas < self.quantidade:
            self.status = 'ativo'
            self.save(update_fields=['status', 'atualizado_em'])


class BloqueioAgenda(ClinicaModel):
    """Bloqueio de horários (férias, reunião, feriado...). Sem profissional = bloqueia a clínica toda."""
    medico = models.ForeignKey(Medico, on_delete=models.CASCADE, null=True, blank=True, related_name='bloqueios',
                               verbose_name='Profissional', help_text='Vazio = todos os profissionais.')
    inicio = models.DateTimeField('Início')
    fim = models.DateTimeField('Fim')
    motivo = models.CharField(max_length=150)

    class Meta:
        ordering = ['-inicio']
        verbose_name = 'Bloqueio de agenda'

    def __str__(self):
        return f'{self.motivo} ({timezone.localtime(self.inicio):%d/%m %H:%M} - {timezone.localtime(self.fim):%d/%m %H:%M})'

    @classmethod
    def conflitante(cls, clinica, medico, inicio, fim):
        return cls.objects.filter(clinica=clinica, inicio__lt=fim, fim__gt=inicio).filter(
            models.Q(medico=medico) | models.Q(medico__isnull=True)).first()


class ListaEspera(ClinicaModel):
    """Pacientes aguardando vaga/encaixe."""
    STATUS = [('aguardando', 'Aguardando vaga'), ('agendado', 'Agendado'), ('desistiu', 'Desistiu')]
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='espera')
    medico = models.ForeignKey(Medico, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='Profissional desejado')
    tipo = models.ForeignKey(TipoAtendimento, on_delete=models.SET_NULL, null=True, blank=True,
                             verbose_name='Tipo de atendimento')
    preferencia = models.CharField('Preferência de dia/horário', max_length=150, blank=True)
    desde = models.DateField('Na lista desde', default=timezone.localdate)
    prioridade = models.PositiveSmallIntegerField(choices=[(1, 'Alta'), (2, 'Normal'), (3, 'Baixa')], default=2)
    status = models.CharField(max_length=12, choices=STATUS, default='aguardando')
    observacoes = models.TextField('Observações', blank=True)

    class Meta:
        ordering = ['status', 'prioridade', 'desde']
        verbose_name = 'Lista de espera'

    def __str__(self):
        return f'{self.paciente} ({self.get_status_display()})'


class Agendamento(ClinicaModel):
    STATUS = [
        ('agendado', 'Agendado'),
        ('confirmado', 'Confirmado'),
        ('aguardando', 'Presente / aguardando'),
        ('em_atendimento', 'Em atendimento'),
        ('concluido', 'Concluído'),
        ('faltou', 'Faltou'),
        ('cancelado', 'Cancelado'),
    ]
    CORES = {'agendado': '#64748b', 'confirmado': '#0ea5e9', 'aguardando': '#f59e0b',
             'em_atendimento': '#8b5cf6', 'concluido': '#16a34a', 'faltou': '#dc2626', 'cancelado': '#9ca3af'}

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='agendamentos')
    medico = models.ForeignKey(Medico, on_delete=models.PROTECT, related_name='agendamentos',
                               verbose_name='Médico / profissional')
    tipo = models.ForeignKey(TipoAtendimento, on_delete=models.PROTECT, verbose_name='Tipo de atendimento')
    inicio = models.DateTimeField('Início')
    fim = models.DateTimeField('Término', blank=True)
    status = models.CharField(max_length=20, choices=STATUS, default='agendado')
    pacote = models.ForeignKey(PacoteSessao, on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='agendamentos', verbose_name='Pacote de sessões')
    convenio = models.BooleanField('Atendimento por convênio', default=False)
    teleconsulta = models.BooleanField('Teleconsulta (vídeo)', default=False)
    origem = models.CharField(max_length=15, default='recepcao', editable=False,
                              choices=[('recepcao', 'Recepção'), ('online', 'Agendamento online')])
    checkin_em = models.DateTimeField('Check-in digital em', null=True, blank=True, editable=False)
    tele_consentimento_em = models.DateTimeField('Consentimento da teleconsulta em', null=True, blank=True,
                                                 editable=False)
    tele_autoriza_gravacao = models.BooleanField('Paciente autorizou gravação', default=False, editable=False)
    tele_consentimento_ip = models.GenericIPAddressField(null=True, blank=True, editable=False)
    valor = models.DecimalField('Valor (R$)', max_digits=10, decimal_places=2, null=True, blank=True)
    observacoes = models.TextField('Observações', blank=True)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    confirmado_em = models.DateTimeField(null=True, blank=True, editable=False)
    confirmado_por = models.CharField(max_length=20, blank=True, editable=False)
    chegada_em = models.DateTimeField(null=True, blank=True, editable=False)
    atendimento_inicio = models.DateTimeField(null=True, blank=True, editable=False)
    atendimento_fim = models.DateTimeField(null=True, blank=True, editable=False)
    lembrete_enviado = models.BooleanField(default=False, editable=False)
    notificar = models.BooleanField('Notificar paciente (WhatsApp/e-mail)', default=True)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)

    class Meta:
        ordering = ['inicio']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._status_original = self.status
        self._inicio_original = self.inicio

    def __str__(self):
        return f'{timezone.localtime(self.inicio):%d/%m/%Y %H:%M} - {self.paciente}'

    def save(self, *args, **kwargs):
        if self.inicio and not self.fim:
            self.fim = self.inicio + timedelta(minutes=self.tipo.duracao_minutos or 30)
        if not self.pk and self.tipo_id and self.tipo.teleconsulta:
            self.teleconsulta = True
        if self.valor is None and self.tipo_id:
            if self.pacote_id:
                self.valor = 0
            elif self.convenio and self.tipo.valor_convenio is not None:
                self.valor = self.tipo.valor_convenio
            else:
                self.valor = self.tipo.valor
        super().save(*args, **kwargs)

    @property
    def cor(self):
        return self.CORES.get(self.status, '#64748b')

    @property
    def link_confirmacao(self):
        return settings.SITE_URL + reverse('agenda:confirmar_publico', args=[self.token])

    @property
    def link_checkin(self):
        return settings.SITE_URL + reverse('agenda:checkin', args=[self.token])

    @property
    def link_avaliacao(self):
        return settings.SITE_URL + reverse('agenda:avaliar', args=[self.token])

    @property
    def link_teleconsulta(self):
        """Link enviado ao paciente: página com termo de consentimento + sala de vídeo."""
        if not self.teleconsulta:
            return ''
        return settings.SITE_URL + reverse('agenda:teleconsulta', args=[self.token])

    @property
    def sala_video_url(self):
        if not self.teleconsulta:
            return ''
        base = (self.clinica.telemedicina_url or 'https://meet.jit.si').rstrip('/')
        return f'{base}/MedAccess-{self.token.hex[:20]}'

    @property
    def ativo(self):
        return self.status not in ('cancelado', 'faltou')

    @property
    def numero_sessao(self):
        if not self.pacote_id:
            return None
        anteriores = self.pacote.agendamentos.exclude(status='cancelado').filter(inicio__lt=self.inicio).count()
        return anteriores + 1


class AvaliacaoNPS(ClinicaModel):
    """Pesquisa de satisfação pós-atendimento (Net Promoter Score 0-10)."""
    agendamento = models.OneToOneField(Agendamento, on_delete=models.CASCADE, related_name='avaliacao')
    nota = models.PositiveSmallIntegerField('Recomendaria a clínica (0-10)')
    nota_medico = models.PositiveSmallIntegerField('Atendimento do profissional (0-10)', null=True, blank=True)
    nota_recepcao = models.PositiveSmallIntegerField('Atendimento da recepção (0-10)', null=True, blank=True)
    comentario = models.TextField('Comentário', blank=True)

    class Meta:
        verbose_name = 'Avaliação NPS'

    @property
    def classificacao(self):
        return 'promotor' if self.nota >= 9 else ('neutro' if self.nota >= 7 else 'detrator')
