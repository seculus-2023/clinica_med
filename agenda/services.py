from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Agendamento, ListaEspera


def avisar_lista_espera(ag):
    """Horário liberado: avisa a recepção se há pacientes na lista de espera compatíveis."""
    from django.db.models import Q
    from django.urls import reverse

    from contas.models import Lembrete
    if ag.inicio <= timezone.now():
        return
    espera = ListaEspera.objects.filter(clinica=ag.clinica, status='aguardando').filter(
        Q(medico=ag.medico) | Q(medico__isnull=True)).filter(Q(tipo=ag.tipo) | Q(tipo__isnull=True))
    n = espera.count()
    if n:
        nomes = ', '.join(str(e.paciente) for e in espera.select_related('paciente')[:5])
        Lembrete.objects.create(
            clinica=ag.clinica, origem='lista_espera',
            titulo=f'Horário liberado {timezone.localtime(ag.inicio):%d/%m %H:%M} ({ag.medico}) — {n} na lista de espera',
            mensagem=f'Encaixe sugerido: {nomes}', link=reverse('agenda:espera_list'))


def mudar_status(ag, novo, origem='recepcao'):
    agora = timezone.now()
    ag.status = novo
    if novo == 'confirmado' and not ag.confirmado_em:
        ag.confirmado_em = agora
        ag.confirmado_por = origem
    elif novo == 'aguardando' and not ag.chegada_em:
        ag.chegada_em = agora
    elif novo == 'em_atendimento':
        ag.atendimento_inicio = ag.atendimento_inicio or agora
    elif novo == 'concluido':
        ag.atendimento_fim = ag.atendimento_fim or agora
    ag.save()


@receiver(post_save, sender=Agendamento)
def apos_salvar_agendamento(sender, instance, created, **kwargs):
    from callcenter.services import criar_contato_falta, criar_contato_pos_consulta, criar_contato_retorno
    from notificacoes.services import notificar_agendamento

    ag = instance
    status_ant, inicio_ant = ag._status_original, ag._inicio_original
    if created:
        if ag.notificar and ag.status not in ('cancelado',):
            notificar_agendamento(ag, 'agendamento')
    else:
        if ag.status == 'cancelado' and status_ant != 'cancelado':
            if ag.notificar:
                notificar_agendamento(ag, 'cancelamento')
        elif inicio_ant and ag.inicio != inicio_ant and ag.ativo:
            Agendamento.objects.filter(pk=ag.pk).update(lembrete_enviado=False)
            ag.lembrete_enviado = False
            if ag.notificar:
                notificar_agendamento(ag, 'reagendamento')
        if ag.status != status_ant:
            from estoque.services import baixar_insumos, estornar_insumos
            if ag.status == 'concluido':
                criar_contato_pos_consulta(ag)
                criar_contato_retorno(ag)
                baixar_insumos(ag)
                if ag.clinica.enviar_nps and ag.notificar:
                    notificar_agendamento(ag, 'nps')
            elif status_ant == 'concluido':
                estornar_insumos(ag)
            if ag.status == 'faltou':
                criar_contato_falta(ag)
            if ag.status == 'cancelado':
                avisar_lista_espera(ag)
    if ag.pacote_id:
        ag.pacote.atualizar_status()
    ag._status_original, ag._inicio_original = ag.status, ag.inicio
