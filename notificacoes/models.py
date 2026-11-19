from django.db import models

from contas.models import ClinicaModel


class Notificacao(ClinicaModel):
    CANAIS = [('whatsapp', 'WhatsApp'), ('email', 'E-mail'), ('sms', 'SMS')]
    STATUS = [('pendente', 'Pendente'), ('enviado', 'Enviado'), ('simulado', 'Simulado'), ('erro', 'Erro')]
    canal = models.CharField(max_length=10, choices=CANAIS)
    evento = models.CharField(max_length=30, blank=True)
    remetente = models.CharField(max_length=200, blank=True)
    destinatario = models.CharField(max_length=200)
    nome_destinatario = models.CharField(max_length=150, blank=True)
    assunto = models.CharField(max_length=200, blank=True)
    mensagem = models.TextField()
    status = models.CharField(max_length=10, choices=STATUS, default='pendente')
    erro = models.TextField(blank=True)
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='notificacoes')
    enviado_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Notificação'
        verbose_name_plural = 'Notificações'

    def __str__(self):
        return f'{self.get_canal_display()} -> {self.destinatario}'

    @property
    def link_wame(self):
        from urllib.parse import quote
        if self.canal != 'whatsapp':
            return ''
        return f'https://wa.me/{self.destinatario}?text={quote(self.mensagem)}'


class Campanha(ClinicaModel):
    nome = models.CharField(max_length=120)
    mensagem = models.TextField()
    filtros = models.JSONField(default=dict, blank=True)
    total = models.PositiveIntegerField(default=0)
    criado_por = models.ForeignKey('contas.Usuario', on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return self.nome
