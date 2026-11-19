from .models import Clinica, Vinculo


class ClinicaMiddleware:
    """Define request.clinica e request.vinculo a partir da clínica escolhida na sessão."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.clinica = None
        request.vinculo = None
        user = getattr(request, 'user', None)
        if user is not None and user.is_authenticated:
            cid = request.session.get('clinica_id')
            if cid:
                if user.is_superuser:
                    request.clinica = Clinica.objects.filter(pk=cid).first()
                    request.vinculo = Vinculo.objects.select_related('perfil').filter(
                        usuario=user, clinica_id=cid).first()
                else:
                    v = Vinculo.objects.select_related('clinica', 'perfil').filter(
                        usuario=user, clinica_id=cid, ativo=True, clinica__ativa=True).first()
                    if v:
                        request.clinica = v.clinica
                        request.vinculo = v
                    else:
                        request.session.pop('clinica_id', None)
        from django.utils import timezone
        if request.clinica:
            request.clinica.ativar_fuso()
        else:
            timezone.deactivate()
        return self.get_response(request)
