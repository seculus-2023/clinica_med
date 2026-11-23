"""Mantém a senha coerente quando o atendimento muda na agenda ou no app do médico."""
from django.contrib.auth.signals import user_logged_out
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from agenda.models import Agendamento

from .models import PontoAtendimento, Senha
from .services import STATUS_ATIVOS, hoje

SINCRONIA = {
    'em_atendimento': (('aguardando', 'chamada'), 'em_atendimento', 'inicio_em'),
    'concluido': (('aguardando', 'chamada', 'em_atendimento'), 'concluida', 'fim_em'),
    'faltou': (('aguardando', 'chamada'), 'ausente', 'fim_em'),
    'cancelado': (('aguardando', 'chamada'), 'cancelada', 'fim_em'),
}


@receiver(user_logged_out)
def liberar_guiche_ao_sair(sender, request, user, **kwargs):
    """Ao sair do sistema, libera o guichê. Com senha em andamento, ele fica reservado até o gestor liberar."""
    if user is None:
        return
    for ponto in PontoAtendimento.objects.filter(operador=user).select_related('clinica'):
        ativa = Senha.objects.filter(clinica=ponto.clinica, data=hoje(ponto.clinica), ponto=ponto,
                                     status__in=STATUS_ATIVOS).exists()
        if not ativa:
            PontoAtendimento.objects.filter(pk=ponto.pk).update(operador=None, operador_desde=None,
                                                                atualizado_em=timezone.now())


@receiver(post_save, sender=Agendamento)
def sincronizar_senha(sender, instance, created, **kwargs):
    regra = SINCRONIA.get(instance.status)
    if created or not regra:
        return
    origens, destino, campo = regra
    agora = timezone.now()
    Senha.objects.filter(agendamento=instance, status__in=origens).update(
        status=destino, atualizado_em=agora, **{campo: agora})
