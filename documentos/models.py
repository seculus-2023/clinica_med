import uuid

from django.db import models
from django.utils import timezone

from cadastros.models import Medicamento, Medico, Paciente
from clinica.armazenamento import privado
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

def gerar_codigo():
    """Código de verificação aleatório no formato XXXX-XXXX-XXXX-XXXX."""
    import secrets
    h = secrets.token_hex(8).upper()
    return '-'.join(h[i:i + 4] for i in range(0, 16, 4))


def url_verificacao(codigo=''):
    from django.conf import settings
    from django.urls import reverse
    base = settings.SITE_URL + reverse('documentos:verificar')
    return f'{base}?codigo={codigo}' if codigo else base


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
    codigo_verificacao = models.CharField('Código de verificação', max_length=19, blank=True, db_index=True,
                                          editable=False)
    visivel_paciente = models.BooleanField('Disponível no portal do paciente', default=True)

    class Meta:
        ordering = ['-data']

    def save(self, *args, **kwargs):
        if not self.codigo_verificacao:
            self.codigo_verificacao = gerar_codigo()
        super().save(*args, **kwargs)

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


class DocumentoAssinado(ClinicaModel):
    """PDF assinado eletronicamente na tela 'Assinar documento' (imagem da assinatura + certificação lateral)."""
    medico = models.ForeignKey(Medico, on_delete=models.PROTECT, related_name='documentos_assinados',
                               verbose_name='Assinado por')
    paciente = models.ForeignKey(Paciente, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='documentos_assinados')
    nome_arquivo = models.CharField('Documento', max_length=200)
    arquivo = models.FileField(upload_to='assinados/%Y/%m/', storage=privado)
    codigo = models.CharField('Código de verificação', max_length=19, unique=True)
    sha256 = models.CharField('Hash SHA-256 do PDF assinado', max_length=64)
    sha256_original = models.CharField('Hash SHA-256 do original', max_length=64, blank=True)
    paginas = models.PositiveIntegerField(default=1)
    assinado_em = models.DateTimeField()
    usuario = models.ForeignKey('contas.Usuario', on_delete=models.SET_NULL, null=True, related_name='+')
    ip = models.GenericIPAddressField(null=True, blank=True)
    anexo = models.ForeignKey('prontuario.Anexo', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-assinado_em']
        verbose_name = 'Documento assinado'
        verbose_name_plural = 'Documentos assinados'

    def __str__(self):
        return f'{self.nome_arquivo} ({self.codigo})'
