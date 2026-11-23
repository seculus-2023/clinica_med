from django.conf import settings
from django.shortcuts import redirect

LIVRES = ('/conta/', '/assinatura/', '/static/', '/media/', '/sw.js', '/manifest.webmanifest', '/offline/',
          '/agenda/c/', '/agenda/online/', '/agenda/checkin/', '/agenda/avaliar/', '/agenda/tele/', '/portal/',
          '/documentos/verificar/', '/notificacoes/webhook/', '/admin/',
          '/medico/manifest.webmanifest', '/senhas/tv/')


class AssinaturaMiddleware:
    """Com SAAS_ATIVO=1, bloqueia o uso interno da clínica com assinatura cancelada/suspensa/vencida."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (getattr(settings, 'SAAS_ATIVO', False) and getattr(request, 'clinica', None)
                and request.user.is_authenticated and not request.user.is_superuser
                and not request.path.startswith(LIVRES)):
            a = getattr(request.clinica, 'assinatura', None)
            if a is not None and a.bloqueada:
                return redirect('assinaturas:bloqueado')
        return self.get_response(request)
