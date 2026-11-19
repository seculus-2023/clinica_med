from datetime import timedelta

from django.utils import timezone

from .models import ContatoPaciente


def criar_contato_pos_consulta(ag):
    if ContatoPaciente.objects.filter(agendamento=ag, motivo='pos_consulta').exists():
        return None
    dias = ag.clinica.callcenter_dias_apos
    return ContatoPaciente.objects.create(
        clinica=ag.clinica, paciente=ag.paciente, medico=ag.medico, agendamento=ag, motivo='pos_consulta',
        data_prevista=timezone.localtime(ag.inicio).date() + timedelta(days=dias),
        observacoes=f'Atendimento: {ag.tipo} em {timezone.localtime(ag.inicio):%d/%m/%Y %H:%M}.')


def agendar_retorno(paciente, medico, data_retorno, agendamento=None, origem=''):
    """Cria/atualiza o alerta de retorno (contato 7 dias antes da data sugerida)."""
    data_contato = max(data_retorno - timedelta(days=7), timezone.localdate())
    existente = ContatoPaciente.objects.filter(paciente=paciente, motivo='retorno', agendamento=agendamento,
                                               status__in=('pendente', 'sem_resposta')).first()
    obs = f'Retorno sugerido para {data_retorno:%d/%m/%Y}. {origem}'.strip()
    if existente:
        existente.data_prevista, existente.observacoes = data_contato, obs
        existente.save(update_fields=['data_prevista', 'observacoes', 'atualizado_em'])
        return existente
    return ContatoPaciente.objects.create(clinica=paciente.clinica, paciente=paciente, medico=medico,
                                          agendamento=agendamento, motivo='retorno', data_prevista=data_contato,
                                          observacoes=obs)


def criar_contato_retorno(ag):
    if ag.tipo.retorno_dias:
        data = timezone.localtime(ag.inicio).date() + timedelta(days=ag.tipo.retorno_dias)
        agendar_retorno(ag.paciente, ag.medico, data, ag, f'({ag.tipo})')


def criar_contato_falta(ag):
    if ContatoPaciente.objects.filter(agendamento=ag, motivo='faltou').exists():
        return None
    return ContatoPaciente.objects.create(
        clinica=ag.clinica, paciente=ag.paciente, medico=ag.medico, agendamento=ag, motivo='faltou', prioridade=1,
        data_prevista=timezone.localdate(),
        observacoes=f'Faltou ao atendimento {ag.tipo} de {timezone.localtime(ag.inicio):%d/%m/%Y %H:%M}. '
                    'Entrar em contato para reagendar.')
