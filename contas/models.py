import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone

MODULOS = [
    ('dashboard', 'Dashboard'),
    ('agenda', 'Agenda'),
    ('cadastros', 'Cadastros'),
    ('sessoes', 'Pacotes de sessões'),
    ('estoque', 'Estoque'),
    ('financeiro', 'Financeiro'),
    ('convenios', 'Convênios e faturamento TISS'),
    ('prontuario', 'Prontuário eletrônico'),
    ('documentos', 'Prescrições e documentos'),
    ('callcenter', 'Call center'),
    ('relatorios', 'Relatórios'),
    ('administrativo', 'Administrativo'),
]
NIVEIS = [('nenhum', 'Sem acesso'), ('ver', 'Visualizar'), ('editar', 'Visualizar e editar')]
ORDEM_NIVEL = {'nenhum': 0, 'ver': 1, 'editar': 2}

MSG_AGENDAMENTO = (
    'Olá {paciente}! Seu atendimento ({tipo}) na {clinica} foi agendado para '
    '{data} às {hora} com {medico}.\nConfirme sua presença: {link_confirmacao}'
)
MSG_LEMBRETE = (
    'Olá {paciente}! Lembrete: você tem {tipo} na {clinica} em {data} às {hora} '
    'com {medico}.\nConfirme ou cancele: {link_confirmacao}'
)
MSG_CANCELAMENTO = ('Olá {paciente}, seu atendimento de {data} às {hora} na {clinica} foi cancelado. '
                    'Para reagendar, fale conosco.')
MSG_POS_CONSULTA = ('Olá {paciente}! Aqui é da {clinica}. Como você está após o atendimento com {medico}? '
                    'Ficamos à disposição.')
MSG_NPS = ('Olá {paciente}! Obrigado por escolher a {clinica}. Em 30 segundos, avalie seu atendimento com {medico}: '
           '{link_avaliacao}')
MSG_ANIVERSARIO = 'Feliz aniversário, {paciente}! 🎉 A equipe da {clinica} deseja muita saúde e alegria.'


class Clinica(models.Model):
    PROVEDORES = [
        ('simulado', 'Simulado (apenas registra, gera link wa.me)'),
        ('meta', 'WhatsApp Cloud API (Meta)'),
        ('evolution', 'Evolution API'),
        ('zapi', 'Z-API'),
        ('webhook', 'Webhook genérico (POST JSON)'),
    ]
    nome = models.CharField('Nome fantasia', max_length=150)
    razao_social = models.CharField('Razão social', max_length=200, blank=True)
    cnpj = models.CharField('CNPJ', max_length=20, blank=True)
    cnes = models.CharField('CNES', max_length=7, blank=True, help_text='Cadastro Nacional de Estabelecimentos de Saúde (TISS).')
    telefone = models.CharField(max_length=20, blank=True)
    whatsapp = models.CharField('WhatsApp da clínica', max_length=20, blank=True,
                                help_text='Número remetente das mensagens enviadas aos pacientes e médicos.')
    email = models.EmailField('E-mail', blank=True)
    endereco = models.CharField('Endereço', max_length=250, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField('UF', max_length=2, blank=True)
    logo = models.ImageField(upload_to='logos/', blank=True, null=True)
    FUSOS = [('America/Sao_Paulo', 'Brasília (SP, RJ, MG, Sul, Nordeste, GO, DF)'),
             ('America/Manaus', 'Amazonas, Rondônia, Roraima (UTC-4)'),
             ('America/Cuiaba', 'Mato Grosso (UTC-4)'), ('America/Campo_Grande', 'Mato Grosso do Sul (UTC-4)'),
             ('America/Rio_Branco', 'Acre (UTC-5)'), ('America/Noronha', 'Fernando de Noronha (UTC-2)'),
             ('America/Belem', 'Pará / Amapá (UTC-3)'), ('America/Fortaleza', 'Ceará e Nordeste (UTC-3)')]
    fuso_horario = models.CharField('Fuso horário', max_length=40, choices=FUSOS, default='America/Sao_Paulo')
    ativa = models.BooleanField(default=True)

    lembrete_horas_antes = models.PositiveIntegerField('Lembrete ao paciente (horas antes)', default=24)
    callcenter_dias_apos = models.PositiveIntegerField('Contato pós-consulta (dias após)', default=2)
    notificar_whatsapp = models.BooleanField('Enviar notificações por WhatsApp', default=True)
    notificar_email = models.BooleanField('Enviar notificações por e-mail', default=True)
    whatsapp_provedor = models.CharField('Provedor WhatsApp', max_length=20, choices=PROVEDORES, default='simulado')
    whatsapp_api_url = models.CharField(
        'URL da API WhatsApp', max_length=250, blank=True,
        help_text='Evolution/Z-API/Webhook: URL base. Meta: opcional (padrão graph.facebook.com).')
    whatsapp_instancia = models.CharField(
        'Instância / Phone Number ID', max_length=120, blank=True,
        help_text='Evolution/Z-API: vazio = usa o próprio número de WhatsApp da clínica. Meta: Phone Number ID.')
    whatsapp_token = models.CharField('Token / API key', max_length=300, blank=True)
    webhook_token = models.CharField('Token do webhook (recebimento)', max_length=64, blank=True, editable=False)
    resposta_sim_nao = models.BooleanField('Paciente confirma/cancela respondendo SIM ou NÃO no WhatsApp', default=True)
    email_remetente = models.EmailField('E-mail remetente', blank=True)
    smtp_host = models.CharField('Servidor SMTP', max_length=120, blank=True,
                                 help_text='Opcional: e-mail próprio da clínica (ex.: smtp.gmail.com). Vazio = usa o do .env.')
    smtp_porta = models.PositiveIntegerField('Porta SMTP', default=587)
    smtp_usuario = models.CharField('Usuário SMTP', max_length=150, blank=True)
    smtp_senha = models.CharField('Senha SMTP / senha de app', max_length=200, blank=True)
    smtp_tls = models.BooleanField('Usar TLS', default=True)

    SMS_PROVEDORES = [('nenhum', 'Desativado'), ('twilio', 'Twilio'), ('zenvia', 'Zenvia'),
                      ('webhook', 'Webhook genérico (POST JSON)')]
    notificar_sms = models.BooleanField('Enviar notificações por SMS', default=False)
    sms_provedor = models.CharField('Provedor de SMS', max_length=10, choices=SMS_PROVEDORES, default='nenhum')
    sms_conta = models.CharField('Conta / Account SID', max_length=120, blank=True)
    sms_token = models.CharField('Token / API key do SMS', max_length=300, blank=True)
    sms_remetente = models.CharField('Remetente do SMS', max_length=40, blank=True,
                                     help_text='Twilio: número +55...; Zenvia: nome/ID do remetente.')
    sms_url = models.CharField('URL do webhook de SMS', max_length=250, blank=True)

    msg_agendamento = models.TextField('Mensagem de agendamento', default=MSG_AGENDAMENTO)
    msg_lembrete = models.TextField('Mensagem de lembrete', default=MSG_LEMBRETE)
    msg_cancelamento = models.TextField('Mensagem de cancelamento', default=MSG_CANCELAMENTO)
    msg_pos_consulta = models.TextField('Mensagem pós-consulta', default=MSG_POS_CONSULTA)
    msg_nps = models.TextField('Mensagem de pesquisa de satisfação (NPS)', default=MSG_NPS)
    msg_aniversario = models.TextField('Mensagem de aniversário', default=MSG_ANIVERSARIO)
    enviar_nps = models.BooleanField('Enviar pesquisa de satisfação após o atendimento', default=True)
    enviar_aniversario = models.BooleanField('Enviar felicitações de aniversário', default=True)

    codigo_publico = models.UUIDField('Código do link público', default=uuid.uuid4, unique=True, editable=False)
    agendamento_online = models.BooleanField('Agendamento online ativo', default=True)
    online_antecedencia_horas = models.PositiveIntegerField('Antecedência mínima online (horas)', default=2)
    online_dias = models.PositiveIntegerField('Agenda online: dias à frente', default=30)
    telemedicina_url = models.CharField(
        'Servidor de vídeo (teleconsulta)', max_length=200, default='https://meet.jit.si',
        help_text='Jitsi Meet. Para sigilo e sem limites, use um servidor Jitsi próprio (ex.: https://video.suaclinica.com.br).')
    google_avaliacao_url = models.URLField(
        'Link de avaliação no Google', blank=True,
        help_text='Pacientes que derem nota 9 ou 10 na pesquisa são convidados a avaliar a clínica no Google.')
    taxa_credito = models.DecimalField('Taxa cartão de crédito (%)', max_digits=5, decimal_places=2, default=0)
    taxa_debito = models.DecimalField('Taxa cartão de débito (%)', max_digits=5, decimal_places=2, default=0)

    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Clínica'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def ativar_fuso(self):
        from django.utils import timezone
        try:
            timezone.activate(self.fuso_horario or settings.TIME_ZONE)
        except Exception:  # noqa: BLE001 - fuso inválido: mantém o padrão
            timezone.deactivate()


class Usuario(AbstractUser):
    telefone = models.CharField('Celular / WhatsApp', max_length=20, blank=True)

    class Meta:
        verbose_name = 'Usuário'

    def __str__(self):
        return self.get_full_name() or self.username


class ClinicaModel(models.Model):
    """Base para todo dado que pertence a uma clínica (multi-clínica)."""
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='+', editable=False)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Perfil(ClinicaModel):
    nome = models.CharField(max_length=80)
    descricao = models.CharField('Descrição', max_length=200, blank=True)
    permissoes = models.JSONField(default=dict, blank=True)
    apenas_propria_agenda = models.BooleanField(
        'Médico vê apenas a própria agenda', default=False,
        help_text='Se o usuário estiver vinculado a um médico, verá somente os próprios atendimentos.')

    class Meta:
        verbose_name = 'Perfil de acesso'
        verbose_name_plural = 'Perfis de acesso'
        ordering = ['nome']

    def __str__(self):
        return self.nome

    def nivel(self, modulo):
        return self.permissoes.get(modulo, 'nenhum')


class Vinculo(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='vinculos')
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='vinculos')
    perfil = models.ForeignKey(Perfil, on_delete=models.PROTECT, related_name='vinculos')
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('usuario', 'clinica')
        verbose_name = 'Vínculo usuário x clínica'

    def __str__(self):
        return f'{self.usuario} @ {self.clinica} ({self.perfil})'


class Lembrete(ClinicaModel):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True,
                                related_name='lembretes', verbose_name='Para',
                                help_text='Deixe vazio para todos os usuários da clínica.')
    titulo = models.CharField('Título', max_length=150)
    mensagem = models.TextField(blank=True)
    data_hora = models.DateTimeField('Lembrar em', default=timezone.now)
    link = models.CharField(max_length=250, blank=True, editable=False)
    origem = models.CharField(max_length=20, default='manual', editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)
    concluido = models.BooleanField('Concluído', default=False)
    enviar_email = models.BooleanField('Também enviar por e-mail', default=False)
    email_enviado = models.BooleanField(default=False, editable=False)

    class Meta:
        ordering = ['concluido', 'data_hora']

    def __str__(self):
        return self.titulo
