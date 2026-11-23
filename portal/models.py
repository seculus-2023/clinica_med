from django.db import models

from contas.models import ClinicaModel


class AvisoPaciente(ClinicaModel):
    """Aviso enviado pelo paciente à clínica pelo app."""
    TIPOS = [('atraso', 'Vou me atrasar'), ('nao_comparecer', 'Não poderei comparecer'),
             ('remarcar', 'Quero remarcar'), ('duvida', 'Tenho uma dúvida'), ('outro', 'Outro assunto')]
    paciente = models.ForeignKey('cadastros.Paciente', on_delete=models.CASCADE, related_name='avisos_app')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='avisos_app', verbose_name='Consulta relacionada')
    tipo = models.CharField('Assunto', max_length=15, choices=TIPOS)
    mensagem = models.CharField('Mensagem', max_length=500)

    class Meta:
        ordering = ['-criado_em']
        verbose_name = 'Aviso do paciente'
        verbose_name_plural = 'Avisos dos pacientes'

    def __str__(self):
        return f'{self.get_tipo_display()} - {self.paciente}'
