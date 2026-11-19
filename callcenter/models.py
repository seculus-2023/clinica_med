from django.conf import settings
from django.db import models
from django.utils import timezone

from cadastros.models import Medico, Paciente
from contas.models import ClinicaModel


class ContatoPaciente(ClinicaModel):
    MOTIVOS = [('pos_consulta', 'Pós-consulta'), ('faltou', 'Paciente faltou'), ('retorno', 'Agendar retorno'),
               ('pesquisa', 'Pesquisa de satisfação'), ('pacote', 'Renovação de pacote'), ('outro', 'Outro')]
    STATUS = [('pendente', 'Pendente'), ('em_andamento', 'Em andamento'), ('sem_resposta', 'Sem resposta'),
              ('contatado', 'Contatado'), ('reagendado', 'Reagendado'), ('encerrado', 'Encerrado')]
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='contatos')
    medico = models.ForeignKey(Medico, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='Profissional')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='contatos', editable=False)
    motivo = models.CharField(max_length=20, choices=MOTIVOS, default='pos_consulta')
    data_prevista = models.DateField('Contatar em', default=timezone.localdate)
    status = models.CharField(max_length=20, choices=STATUS, default='pendente')
    prioridade = models.PositiveSmallIntegerField(choices=[(1, 'Alta'), (2, 'Normal'), (3, 'Baixa')], default=2)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+')
    tentativas = models.PositiveIntegerField(default=0, editable=False)
    satisfacao = models.PositiveSmallIntegerField('Satisfação (1 a 5)', null=True, blank=True,
                                                  choices=[(i, str(i)) for i in range(1, 6)])
    observacoes = models.TextField('Observações', blank=True)
    concluido_em = models.DateTimeField(null=True, blank=True, editable=False)

    class Meta:
        ordering = ['data_prevista', 'prioridade', 'id']
        verbose_name = 'Contato com paciente'

    def __str__(self):
        return f'{self.get_motivo_display()} - {self.paciente}'

    @property
    def aberto(self):
        return self.status in ('pendente', 'em_andamento', 'sem_resposta')

    @property
    def atrasado(self):
        return self.aberto and self.data_prevista < timezone.localdate()


class InteracaoContato(models.Model):
    CANAIS = [('telefone', 'Telefone'), ('whatsapp', 'WhatsApp'), ('email', 'E-mail'), ('presencial', 'Presencial')]
    RESULTADOS = [('contatado', 'Falou com o paciente'), ('sem_resposta', 'Não atendeu / sem resposta'),
                  ('reagendado', 'Reagendou'), ('recado', 'Deixou recado'), ('encerrado', 'Encerrar contato')]
    contato = models.ForeignKey(ContatoPaciente, on_delete=models.CASCADE, related_name='interacoes')
    data = models.DateTimeField(default=timezone.now)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    canal = models.CharField(max_length=15, choices=CANAIS, default='telefone')
    resultado = models.CharField(max_length=15, choices=RESULTADOS, default='contatado')
    anotacao = models.TextField('Anotação', blank=True)

    class Meta:
        ordering = ['-data']
