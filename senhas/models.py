"""Senhas de atendimento: fila do dia, chamadas por voz e painel de TV."""
import uuid

from django.conf import settings
from django.db import models
from django.urls import reverse

from contas.models import Clinica, ClinicaModel

# Nome falado de cada letra: evita que a voz leia "A" e "E" como palavras
LETRAS_FALADAS = {
    'A': 'á', 'B': 'bê', 'C': 'cê', 'D': 'dê', 'E': 'é', 'F': 'éfe', 'G': 'gê', 'H': 'agá', 'I': 'í', 'J': 'jota',
    'K': 'cá', 'L': 'éle', 'M': 'ême', 'N': 'êne', 'O': 'ó', 'Q': 'quê', 'R': 'érre', 'S': 'ésse', 'T': 'tê',
    'U': 'ú', 'V': 'vê', 'W': 'dáblio', 'X': 'xis', 'Y': 'ípsilon', 'Z': 'zê',
}


class ServicoSenha(ClinicaModel):
    """Tipo de fila (recepção, convênios, exames...). A letra identifica a senha: A001, C002..."""
    nome = models.CharField(max_length=60)
    prefixo = models.CharField('Letra da senha', max_length=1,
                               help_text='Uma letra, exceto P (reservada para preferencial).')
    ordem = models.PositiveSmallIntegerField('Ordem', default=1)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['ordem', 'nome']
        verbose_name = 'Serviço de senha'
        verbose_name_plural = 'Serviços de senha'
        constraints = [models.UniqueConstraint(fields=['clinica', 'prefixo'], name='senha_servico_prefixo_unico')]

    def __str__(self):
        return f'{self.prefixo} - {self.nome}'


class PontoAtendimento(ClinicaModel):
    """Guichê ou mesa de onde a senha é chamada."""
    nome = models.CharField(max_length=60, help_text='É o que aparece na TV e é falado. Ex.: Guichê 1.')
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Guichê'
        verbose_name_plural = 'Guichês'

    def __str__(self):
        return self.nome


class ConfigPainel(models.Model):
    clinica = models.OneToOneField(Clinica, on_delete=models.CASCADE, related_name='painel_senhas', editable=False)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    titulo = models.CharField('Título na TV', max_length=80, blank=True, help_text='Vazio = nome da clínica.')
    mensagem = models.CharField('Mensagem no rodapé', max_length=250, blank=True,
                                default='Aguarde sua senha ser chamada. Atendimento preferencial conforme a lei.')
    voz_ativa = models.BooleanField('Chamar por voz', default=True)
    repeticoes = models.PositiveSmallIntegerField('Repetições da voz', default=2,
                                                  choices=[(1, '1 vez'), (2, '2 vezes'), (3, '3 vezes')])

    class Meta:
        verbose_name = 'Painel de TV'

    def __str__(self):
        return f'Painel - {self.clinica}'

    @property
    def caminho_tv(self):
        return reverse('senhas:tv', args=[self.token])


class Senha(ClinicaModel):
    STATUS = [
        ('aguardando', 'Aguardando'),
        ('chamada', 'Chamada'),
        ('em_atendimento', 'Em atendimento'),
        ('concluida', 'Concluída'),
        ('ausente', 'Não compareceu'),
        ('cancelada', 'Cancelada'),
    ]
    servico = models.ForeignKey(ServicoSenha, on_delete=models.PROTECT, related_name='senhas')
    data = models.DateField(db_index=True)
    numero = models.PositiveIntegerField()
    preferencial = models.BooleanField(default=False)
    codigo = models.CharField(max_length=8)
    status = models.CharField(max_length=15, choices=STATUS, default='aguardando')
    paciente = models.ForeignKey('cadastros.Paciente', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='senhas')
    agendamento = models.OneToOneField('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='senha_fila')
    ponto = models.ForeignKey(PontoAtendimento, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name='senhas')
    local = models.CharField('Local da chamada', max_length=120, blank=True)
    vezes_chamada = models.PositiveSmallIntegerField(default=0)
    chamada_em = models.DateTimeField(null=True, blank=True)
    inicio_em = models.DateTimeField(null=True, blank=True)
    fim_em = models.DateTimeField(null=True, blank=True)
    emitida_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')

    class Meta:
        ordering = ['-preferencial', 'criado_em', 'id']
        constraints = [models.UniqueConstraint(fields=['clinica', 'data', 'servico', 'preferencial', 'numero'],
                                               name='senha_numero_unico_dia')]
        indexes = [models.Index(fields=['clinica', 'data', 'status'], name='senha_fila_idx')]

    def __str__(self):
        return self.codigo

    @property
    def texto_fala(self):
        letra = LETRAS_FALADAS.get(self.codigo[:1], self.codigo[:1])
        tipo = 'preferencial ' if self.preferencial else ''
        return f'Senha {tipo}{letra}, {self.numero}. {self.local}.'


class ChamadaSenha(models.Model):
    """Cada chamada (ou rechamada) é um evento: a TV lê os novos e fala um a um."""
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='+')
    senha = models.ForeignKey(Senha, on_delete=models.CASCADE, related_name='chamadas')
    local = models.CharField(max_length=120)
    texto = models.CharField(max_length=220)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-id']
        indexes = [models.Index(fields=['clinica', '-id'], name='senha_chamada_idx')]
