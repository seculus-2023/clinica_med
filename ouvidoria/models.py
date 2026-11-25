"""Ouvidoria: reclamações, sugestões, elogios, denúncias e solicitações, com protocolo, prazo e tramitação."""
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils import timezone

from contas.models import Clinica, ClinicaModel

STATUS_ABERTOS = ('nova', 'em_analise', 'encaminhada')


class ConfigOuvidoria(models.Model):
    clinica = models.OneToOneField(Clinica, on_delete=models.CASCADE, related_name='ouvidoria', editable=False)
    formulario_publico = models.BooleanField('Receber manifestações pelo site (formulário público)', default=True)
    permitir_anonimo = models.BooleanField('Permitir manifestação anônima', default=True)
    prazo_dias = models.PositiveSmallIntegerField(
        'Prazo de resposta (dias corridos)', default=10,
        help_text='Contado a partir do registro. A Lei 13.460/2017 (serviço público) usa 30 dias; clínicas privadas '
                  'costumam adotar de 5 a 10.')
    prorrogacao_dias = models.PositiveSmallIntegerField('Prorrogação máxima (dias)', default=10)
    ouvidor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+', verbose_name='Ouvidor(a) responsável',
                                help_text='Recebe os alertas de novas manifestações. Vazio = todos com acesso '
                                          'de edição à ouvidoria.')
    email_alerta = models.EmailField('E-mail para alertas', blank=True,
                                     help_text='Opcional: recebe um aviso a cada nova manifestação.')
    abrir_por_nps = models.BooleanField(
        'Abrir manifestação quando a pesquisa de satisfação tiver nota baixa com comentário', default=True)
    concluir_sem_retorno_dias = models.PositiveSmallIntegerField(
        'Concluir respondidas sem retorno após (dias)', default=15,
        help_text='Manifestações respondidas sem retorno do manifestante são concluídas automaticamente. 0 = nunca.')
    apresentacao = models.TextField(
        'Texto de apresentação', blank=True,
        default='Este é o canal oficial para você registrar reclamações, sugestões, elogios, denúncias e '
                'solicitações. Toda manifestação recebe um número de protocolo e é respondida dentro do prazo.')
    ano = models.PositiveSmallIntegerField(default=0, editable=False)
    ultimo_numero = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        verbose_name = 'Configuração da ouvidoria'

    def __str__(self):
        return f'Ouvidoria - {self.clinica}'


class Setor(ClinicaModel):
    nome = models.CharField(max_length=80)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', verbose_name='Responsável',
                                    help_text='Sugerido automaticamente ao encaminhar manifestações deste setor.')
    publico = models.BooleanField('Aparece no formulário público', default=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Setor'
        verbose_name_plural = 'Setores'
        constraints = [models.UniqueConstraint(fields=['clinica', 'nome'], name='ouv_setor_nome_unico')]

    def __str__(self):
        return self.nome


class Manifestacao(ClinicaModel):
    TIPOS = [('reclamacao', 'Reclamação'), ('sugestao', 'Sugestão'), ('elogio', 'Elogio'),
             ('denuncia', 'Denúncia'), ('solicitacao', 'Solicitação'), ('informacao', 'Pedido de informação')]
    CANAIS = [('site', 'Site (formulário)'), ('app', 'App do paciente'), ('presencial', 'Presencial'),
              ('telefone', 'Telefone'), ('email', 'E-mail'), ('whatsapp', 'WhatsApp'),
              ('nps', 'Pesquisa de satisfação'), ('redes', 'Redes sociais / sites de reclamação'),
              ('outro', 'Outro')]
    STATUS = [('nova', 'Nova'), ('em_analise', 'Em análise'), ('encaminhada', 'Encaminhada ao setor'),
              ('respondida', 'Respondida'), ('concluida', 'Concluída'), ('arquivada', 'Arquivada')]
    RELACOES = [('paciente', 'Paciente'), ('responsavel', 'Responsável / familiar'),
                ('acompanhante', 'Acompanhante'), ('colaborador', 'Colaborador'), ('outro', 'Outro')]
    PRIORIDADES = [(1, 'Alta'), (2, 'Normal'), (3, 'Baixa')]
    CONCLUSOES = [('procedente', 'Procedente'), ('parcial', 'Parcialmente procedente'),
                  ('improcedente', 'Improcedente'), ('atendida', 'Atendida / informada'),
                  ('registrada', 'Registrada (elogio / sugestão)')]

    protocolo = models.CharField(max_length=12, editable=False)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    chave_hash = models.CharField(max_length=64, editable=False, blank=True)
    tipo = models.CharField(max_length=15, choices=TIPOS)
    canal = models.CharField(max_length=10, choices=CANAIS, default='presencial')
    assunto = models.CharField(max_length=150)
    descricao = models.TextField('Relato')
    data_ocorrido = models.DateField('Data do ocorrido', null=True, blank=True)
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, related_name='manifestacoes',
                              verbose_name='Setor envolvido')
    medico = models.ForeignKey('cadastros.Medico', on_delete=models.SET_NULL, null=True, blank=True,
                               related_name='manifestacoes', verbose_name='Profissional envolvido')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='manifestacoes', editable=False)

    anonima = models.BooleanField('Anônima', default=False)
    sigilosa = models.BooleanField('Identidade sob sigilo', default=False,
                                   help_text='Nome e contato ficam visíveis só para quem edita a ouvidoria.')
    paciente = models.ForeignKey('cadastros.Paciente', on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name='manifestacoes')
    nome = models.CharField('Nome do manifestante', max_length=150, blank=True)
    email = models.EmailField('E-mail', blank=True)
    telefone = models.CharField('Celular / WhatsApp', max_length=20, blank=True)
    relacao = models.CharField('Relação com a clínica', max_length=15, choices=RELACOES, blank=True)
    aceita_contato = models.BooleanField('Aceita ser contatado(a)', default=True)

    status = models.CharField(max_length=12, choices=STATUS, default='nova')
    prioridade = models.PositiveSmallIntegerField(choices=PRIORIDADES, default=2)
    prazo = models.DateField('Prazo de resposta')
    prorrogada = models.BooleanField(default=False, editable=False)
    responsavel = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='manifestacoes_ouvidoria', verbose_name='Responsável atual')
    registrada_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='+', editable=False)
    conclusao = models.CharField('Conclusão', max_length=15, choices=CONCLUSOES, blank=True)
    primeira_resposta_em = models.DateTimeField(null=True, blank=True, editable=False)
    respondida_em = models.DateTimeField(null=True, blank=True, editable=False)
    encerrada_em = models.DateTimeField(null=True, blank=True, editable=False)

    avaliacao_resolvida = models.BooleanField('Teve a demanda resolvida?', null=True, blank=True)
    avaliacao_nota = models.PositiveSmallIntegerField('Satisfação com a resposta (1 a 5)', null=True, blank=True)
    avaliacao_comentario = models.TextField(blank=True)
    avaliada_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Manifestação'
        verbose_name_plural = 'Manifestações'
        constraints = [models.UniqueConstraint(fields=['clinica', 'protocolo'], name='ouv_protocolo_unico')]
        indexes = [models.Index(fields=['clinica', 'status', 'prazo'], name='ouv_fila_idx')]

    def __str__(self):
        return f'{self.protocolo} - {self.get_tipo_display()}'

    @property
    def aberta(self):
        return self.status in STATUS_ABERTOS

    @property
    def encerrada(self):
        return self.status in ('concluida', 'arquivada')

    @property
    def vencida(self):
        return self.aberta and self.prazo < timezone.localdate()

    @property
    def vence_logo(self):
        return self.aberta and not self.vencida and self.prazo <= timezone.localdate() + timedelta(days=2)

    @property
    def dias_restantes(self):
        return (self.prazo - timezone.localdate()).days

    @property
    def identificada(self):
        return not self.anonima and bool(self.nome or self.paciente_id)

    @property
    def nome_exibicao(self):
        if self.anonima:
            return 'Anônimo'
        return self.nome or (self.paciente.nome if self.paciente_id else '-')

    @property
    def caminho_publico(self):
        return reverse('ouvidoria:acompanhar', args=[self.token])


class Andamento(models.Model):
    TIPOS = [('registro', 'Registro'), ('nota', 'Nota interna'), ('encaminhamento', 'Encaminhamento'),
             ('parecer', 'Parecer do setor'), ('resposta', 'Resposta ao manifestante'),
             ('manifestante', 'Mensagem do manifestante'), ('prorrogacao', 'Prorrogação de prazo'),
             ('conclusao', 'Conclusão'), ('arquivamento', 'Arquivamento'), ('reabertura', 'Reabertura'),
             ('avaliacao', 'Avaliação do manifestante')]
    PUBLICOS = ('registro', 'resposta', 'manifestante', 'prorrogacao', 'conclusao', 'arquivamento', 'avaliacao')
    manifestacao = models.ForeignKey(Manifestacao, on_delete=models.CASCADE, related_name='andamentos')
    tipo = models.CharField(max_length=15, choices=TIPOS)
    texto = models.TextField(blank=True)
    publico = models.BooleanField('Visível ao manifestante', default=False)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+')
    destino = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='+', verbose_name='Encaminhado a')
    setor = models.ForeignKey(Setor, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    criado_em = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['criado_em', 'id']

    def __str__(self):
        return f'{self.get_tipo_display()} - {self.manifestacao}'
