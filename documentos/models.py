import uuid

from django.db import models
from django.utils import timezone

from cadastros.models import Medicamento, Medico, Paciente
from contas.models import ClinicaModel

TIPOS = [
    ('receita', 'Receita / prescrição'),
    ('receita_especial', 'Receita de controle especial'),
    ('atestado', 'Atestado médico'),
    ('declaracao', 'Declaração de comparecimento'),
    ('exames', 'Solicitação de exames'),
    ('encaminhamento', 'Encaminhamento'),
    ('laudo', 'Laudo / relatório'),
    ('orientacoes', 'Orientações ao paciente'),
    ('outro', 'Outro documento'),
]

PLACEHOLDERS = ['{paciente}', '{cpf}', '{idade}', '{data}', '{hora}', '{medico}', '{registro}', '{clinica}',
                '{dias}', '{cid}', '{data_atendimento}', '{hora_inicio}', '{hora_fim}']


class ModeloDocumento(ClinicaModel):
    nome = models.CharField(max_length=120)
    tipo = models.CharField(max_length=20, choices=TIPOS)
    conteudo = models.TextField('Conteúdo', help_text='Variáveis: ' + ' '.join(PLACEHOLDERS))
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['tipo', 'nome']
        verbose_name = 'Modelo de documento'

    def __str__(self):
        return self.nome


class Documento(ClinicaModel):
    tipo = models.CharField(max_length=20, choices=TIPOS, default='receita')
    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='documentos')
    medico = models.ForeignKey(Medico, on_delete=models.PROTECT, related_name='documentos',
                               verbose_name='Médico / profissional')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    editable=False)
    atendimento = models.ForeignKey('prontuario.Atendimento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='documentos', editable=False)
    data = models.DateTimeField(default=timezone.now)
    titulo = models.CharField('Título', max_length=150, blank=True)
    conteudo = models.TextField('Texto do documento', blank=True)
    cid = models.CharField('CID', max_length=20, blank=True)
    dias = models.PositiveIntegerField('Dias de afastamento', null=True, blank=True)
    codigo = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    class Meta:
        ordering = ['-data']

    def __str__(self):
        return f'{self.get_tipo_display()} - {self.paciente}'

    @property
    def titulo_exibicao(self):
        return self.titulo or self.get_tipo_display()

    @property
    def tem_itens(self):
        return self.tipo in ('receita', 'receita_especial')

    def preencher(self, texto):
        local = timezone.localtime(self.data)
        ag = self.agendamento
        valores = {
            '{paciente}': self.paciente.nome, '{cpf}': self.paciente.cpf or '',
            '{idade}': str(self.paciente.idade or ''), '{data}': local.strftime('%d/%m/%Y'),
            '{hora}': local.strftime('%H:%M'), '{medico}': self.medico.nome,
            '{registro}': self.medico.registro_completo, '{clinica}': self.clinica.nome,
            '{dias}': str(self.dias or ''), '{cid}': self.cid or '',
            '{data_atendimento}': timezone.localtime(ag.inicio).strftime('%d/%m/%Y') if ag else local.strftime(
                '%d/%m/%Y'),
            '{hora_inicio}': timezone.localtime(ag.inicio).strftime('%H:%M') if ag else '',
            '{hora_fim}': timezone.localtime(ag.fim).strftime('%H:%M') if ag else '',
        }
        for k, v in valores.items():
            texto = texto.replace(k, v)
        return texto


class ItemPrescricao(models.Model):
    documento = models.ForeignKey(Documento, on_delete=models.CASCADE, related_name='itens')
    medicamento = models.ForeignKey(Medicamento, on_delete=models.SET_NULL, null=True, blank=True)
    descricao = models.CharField('Medicamento (texto livre)', max_length=200, blank=True)
    quantidade = models.CharField(max_length=60, blank=True, help_text='Ex.: 1 caixa')
    posologia = models.CharField(max_length=300, blank=True)
    ordem = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['ordem', 'id']

    def __str__(self):
        return self.nome

    @property
    def nome(self):
        return self.descricao or (str(self.medicamento) if self.medicamento else '')
