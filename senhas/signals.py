"""Mantém a senha coerente quando o atendimento muda na agenda ou no app do médico."""
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from agenda.models import Agendamento

from .models import Senha

SINCRONIA = {
    'em_atendimento': (('aguardando', 'chamada'), 'em_atendimento', 'inicio_em'),
    'concluido': (('aguardando', 'chamada', 'em_atendimento'), 'concluida', 'fim_em'),
    'faltou': (('aguardando', 'chamada'), 'ausente', 'fim_em'),
    'cancelado': (('aguardando', 'chamada'), 'cancelada', 'fim_em'),
}


@receiver(post_save, sender=Agendamento)
def sincronizar_senha(sender, instance, created, **kwargs):
    regra = SINCRONIA.get(instance.status)
    if created or not regra:
        return
    origens, destino, campo = regra
    agora = timezone.now()
    Senha.objects.filter(agendamento=instance, status__in=origens).update(
        status=destino, atualizado_em=agora, **{campo: agora})
