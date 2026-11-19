from functools import wraps

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect

from .models import MODULOS, ORDEM_NIVEL


def nivel_acesso(request, modulo):
    user = request.user
    if not user.is_authenticated or getattr(request, 'clinica', None) is None:
        return 'nenhum'
    if user.is_superuser:
        return 'editar'
    if modulo == 'prontuario':
        medico = medico_do_usuario(request)
        if medico is not None:  # parâmetro do cadastro do médico prevalece
            return {'nenhum': 'nenhum', 'consulta': 'ver', 'completo': 'editar'}.get(medico.acesso_prontuario,
                                                                                    'nenhum')
    vinculo = getattr(request, 'vinculo', None)
    if not vinculo:
        return 'nenhum'
    return vinculo.perfil.nivel(modulo)


def medico_do_usuario(request):
    """Médico vinculado ao usuário logado na clínica ativa (cacheado na requisição)."""
    if not hasattr(request, '_medico_usuario'):
        from cadastros.models import Medico
        request._medico_usuario = None
        if request.user.is_authenticated and getattr(request, 'clinica', None):
            request._medico_usuario = Medico.objects.filter(
                clinica=request.clinica, usuario=request.user, ativo=True).first()
    return request._medico_usuario


def tem_permissao(request, modulo, acao='ver'):
    if modulo is None:
        return request.user.is_authenticated and getattr(request, 'clinica', None) is not None
    return ORDEM_NIVEL.get(nivel_acesso(request, modulo), 0) >= ORDEM_NIVEL[acao]


def mapa_permissoes(request):
    return {m: nivel_acesso(request, m) for m, _ in MODULOS}


def medico_restrito(request):
    """Retorna o Médico quando o usuário deve ver apenas a própria agenda."""
    vinculo = getattr(request, 'vinculo', None)
    if request.user.is_superuser or not vinculo or not vinculo.perfil.apenas_propria_agenda:
        return None
    from cadastros.models import Medico
    return Medico.objects.filter(clinica=request.clinica, usuario=request.user).first()


def acesso(modulo, acao='ver'):
    """Decorator para views baseadas em função."""
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect('contas:login')
            if request.clinica is None:
                return redirect('contas:selecionar_clinica')
            if modulo and not tem_permissao(request, modulo, acao):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def superusuario(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('contas:login')
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapper
