from django.conf import settings
from django.db.models import Q
from django.utils import timezone

from .models import Clinica, Lembrete
from .permissoes import mapa_permissoes


def clinica(request):
    ctx = {'PWA_VERSAO': settings.PWA_VERSAO}
    if not getattr(request, 'user', None) or not request.user.is_authenticated:
        return ctx
    ctx['perm'] = mapa_permissoes(request)
    if request.user.is_superuser:
        ctx['minhas_clinicas'] = Clinica.objects.filter(ativa=True)
    else:
        ctx['minhas_clinicas'] = Clinica.objects.filter(
            vinculos__usuario=request.user, vinculos__ativo=True, ativa=True)
    if getattr(request, 'clinica', None):
        pend = Lembrete.objects.filter(
            clinica=request.clinica, concluido=False, data_hora__lte=timezone.now()
        ).filter(Q(usuario=request.user) | Q(usuario__isnull=True))
        ctx['lembretes_pendentes'] = list(pend[:8])
        ctx['lembretes_total'] = pend.count()
    return ctx
