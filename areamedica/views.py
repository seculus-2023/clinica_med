"""Área do médico: aplicativo (PWA) em que o profissional entra e vê os pacientes da sua agenda."""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from agenda.models import Agendamento
from agenda.services import mudar_status
from cadastros.models import Medico
from contas.forms import LoginForm
from contas.models import Clinica
from contas.permissoes import nivel_acesso, tem_permissao

DIAS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
# status que o médico pode marcar nos próprios atendimentos
STATUS_MEDICO = {'aguardando', 'em_atendimento', 'concluido', 'faltou'}


class Entrar(LoginView):
    template_name = 'areamedica/entrar.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_success_url(self):
        prox = self.request.POST.get('next') or self.request.GET.get('next') or ''
        if prox.startswith('/medico/') and url_has_allowed_host_and_scheme(prox, {self.request.get_host()}):
            return prox
        return reverse('areamedica:agenda')


@require_POST
def sair(request):
    logout(request)
    return redirect('areamedica:entrar')


def _clinicas_do_usuario(user):
    if user.is_superuser:
        return Clinica.objects.filter(ativa=True)
    return Clinica.objects.filter(vinculos__usuario=user, vinculos__ativo=True, ativa=True).distinct()


def _preparar(request):
    """Garante login e clínica. Devolve (resposta_de_redirecionamento | None, médico, é_o_próprio_médico)."""
    if not request.user.is_authenticated:
        return redirect(f"{reverse('areamedica:entrar')}?next={request.get_full_path()}"), None, False
    if request.clinica is None:
        clinicas = _clinicas_do_usuario(request.user)
        com_medico = [c for c in clinicas if Medico.objects.filter(clinica=c, usuario=request.user,
                                                                    ativo=True).exists()]
        opcoes = com_medico or list(clinicas)
        if len(opcoes) == 1:
            request.session['clinica_id'] = opcoes[0].pk
            return redirect(request.get_full_path()), None, False
        return redirect('areamedica:clinica'), None, False

    proprio = Medico.objects.filter(clinica=request.clinica, usuario=request.user, ativo=True).first()
    if proprio:
        return None, proprio, True
    # Usuário que não é médico (recepção/administração) pode acompanhar a agenda de um profissional
    if not tem_permissao(request, 'agenda'):
        return render(request, 'areamedica/sem_vinculo.html', status=403), None, False
    medicos = Medico.objects.filter(clinica=request.clinica, ativo=True)
    escolhido = request.GET.get('medico') or request.session.get('am_medico')
    med = medicos.filter(pk=escolhido).first() if str(escolhido or '').isdigit() else None
    med = med or medicos.first()
    if med is None:
        return render(request, 'areamedica/sem_vinculo.html', {'sem_medicos': True}), None, False
    request.session['am_medico'] = med.pk
    return None, med, False


def escolher_clinica(request):
    if not request.user.is_authenticated:
        return redirect('areamedica:entrar')
    clinicas = list(_clinicas_do_usuario(request.user))
    escolha = request.POST.get('id') or request.GET.get('id')
    if escolha and any(str(c.pk) == escolha for c in clinicas):
        request.session['clinica_id'] = int(escolha)
        request.session.pop('am_medico', None)
        return redirect('areamedica:agenda')
    medico_em = set(Medico.objects.filter(usuario=request.user, ativo=True).values_list('clinica_id', flat=True))
    clinicas.sort(key=lambda c: (c.pk not in medico_em, c.nome))
    return render(request, 'areamedica/clinica.html', {'clinicas': clinicas, 'medico_em': medico_em})


def _intervalo(data):
    tz = timezone.get_current_timezone()
    ini = timezone.make_aware(datetime.combine(data, datetime.min.time()), tz)
    return ini, ini + timedelta(days=1)


def _contexto_prontuario(request):
    nivel = nivel_acesso(request, 'prontuario')
    return {'pront_ver': nivel in ('ver', 'editar'), 'pront_editar': nivel == 'editar'}


def agenda(request):
    resp, med, proprio = _preparar(request)
    if resp:
        return resp
    hoje = timezone.localdate()
    data = parse_date(request.GET.get('data', '')) or hoje
    ini, fim = _intervalo(data)
    mostrar_cancelados = request.GET.get('cancelados') == '1'
    qs = (Agendamento.objects.filter(clinica=request.clinica, medico=med, inicio__gte=ini, inicio__lt=fim)
          .select_related('paciente', 'tipo', 'pacote', 'operadora', 'recurso').order_by('inicio'))
    todos = list(qs)
    lista = todos if mostrar_cancelados else [a for a in todos if a.status != 'cancelado']

    contagem = {s: 0 for s, _ in Agendamento.STATUS}
    for a in todos:
        contagem[a.status] += 1
    agora = timezone.now()
    proximo = next((a for a in lista if a.status in ('agendado', 'confirmado', 'aguardando')
                    and a.fim and a.fim >= agora), None) if data == hoje else None

    # faixa da semana com a quantidade de pacientes por dia
    seg = data - timedelta(days=data.weekday())
    w_ini, _ = _intervalo(seg)
    por_dia = {}
    for inicio in (Agendamento.objects.filter(clinica=request.clinica, medico=med, inicio__gte=w_ini,
                                              inicio__lt=w_ini + timedelta(days=7))
                   .exclude(status='cancelado').values_list('inicio', flat=True)):
        d = timezone.localtime(inicio).date()
        por_dia[d] = por_dia.get(d, 0) + 1
    semana = [{'data': seg + timedelta(days=i), 'nome': DIAS[i], 'n': por_dia.get(seg + timedelta(days=i), 0)}
              for i in range(7)]

    ctx = {
        'medico': med, 'proprio': proprio, 'data': data, 'hoje': hoje,
        'anterior': data - timedelta(days=1), 'seguinte': data + timedelta(days=1),
        'semana_anterior': data - timedelta(days=7), 'semana_seguinte': data + timedelta(days=7),
        'semana': semana, 'agendamentos': lista, 'proximo': proximo, 'mostrar_cancelados': mostrar_cancelados,
        'total': len([a for a in todos if a.status != 'cancelado']),
        'aguardando': contagem['aguardando'], 'atendidos': contagem['concluido'],
        'faltas': contagem['faltou'], 'cancelados': contagem['cancelado'],
        'pode_status': proprio or tem_permissao(request, 'agenda', 'editar'),
        'medicos': [] if proprio else Medico.objects.filter(clinica=request.clinica, ativo=True),
        'varias_clinicas': _clinicas_do_usuario(request.user).count() > 1,
        'atualizado': timezone.localtime(),
        'proxima': f"{reverse('areamedica:agenda')}?data={data:%Y-%m-%d}"
                   f"{'&cancelados=1' if mostrar_cancelados else ''}",
        **_contexto_prontuario(request),
    }
    if request.GET.get('parcial') == '1':
        return render(request, 'areamedica/_lista.html', ctx)
    return render(request, 'areamedica/agenda.html', ctx)


def _agendamento(request, pk, med):
    return get_object_or_404(Agendamento.objects.select_related('paciente', 'tipo', 'pacote', 'operadora',
                                                                'plano', 'recurso'),
                             pk=pk, clinica=request.clinica, medico=med)


def paciente(request, pk):
    resp, med, proprio = _preparar(request)
    if resp:
        return resp
    ag = _agendamento(request, pk, med)
    p = ag.paciente
    historico = (Agendamento.objects.filter(clinica=request.clinica, medico=med, paciente=p)
                 .exclude(pk=ag.pk).select_related('tipo').order_by('-inicio'))
    agora = timezone.now()
    return render(request, 'areamedica/paciente.html', {
        'medico': med, 'proprio': proprio, 'a': ag, 'p': p, 'hoje': timezone.localdate(),
        'anteriores': [h for h in historico if h.inicio < agora][:10],
        'futuros': sorted([h for h in historico if h.inicio >= agora and h.ativo], key=lambda h: h.inicio)[:5],
        'pode_status': proprio or tem_permissao(request, 'agenda', 'editar'),
        'proxima': request.path,
        **_contexto_prontuario(request),
    })


@require_POST
def status(request, pk):
    resp, med, proprio = _preparar(request)
    if resp:
        return resp
    ag = _agendamento(request, pk, med)
    novo = request.POST.get('status', '')
    if not (proprio or tem_permissao(request, 'agenda', 'editar')):
        raise PermissionDenied
    if novo not in STATUS_MEDICO:
        raise PermissionDenied
    if ag.status == 'cancelado':
        messages.error(request, 'Este agendamento foi cancelado.')
    else:
        mudar_status(ag, novo, origem='medico')
        if novo == 'em_atendimento' and nivel_acesso(request, 'prontuario') == 'editar':
            return redirect('prontuario:iniciar', ag.pk)
        messages.success(request, f'{ag.paciente.nome}: {ag.get_status_display().lower()}.')
    prox = request.POST.get('next', '')
    if prox.startswith('/medico/'):
        return redirect(prox)
    return redirect(f"{reverse('areamedica:agenda')}?data={timezone.localtime(ag.inicio):%Y-%m-%d}")


@require_POST
def chamar(request, pk):
    """Chama o paciente no painel de TV, por voz."""
    from senhas.services import ErroSenha, chamar_agendamento

    resp, med, proprio = _preparar(request)
    if resp:
        return resp
    if not (proprio or tem_permissao(request, 'agenda', 'editar')):
        raise PermissionDenied
    ag = _agendamento(request, pk, med)
    try:
        senha = chamar_agendamento(ag, request.user)
        messages.success(request, f'Senha {senha.codigo} chamada no painel.')
    except ErroSenha as e:
        messages.error(request, str(e))
    prox = request.POST.get('next', '')
    if prox.startswith('/medico/') and url_has_allowed_host_and_scheme(prox, {request.get_host()}):
        return redirect(prox)
    return redirect('areamedica:agenda')


def manifest(request):
    icone = static('icons/icon-192.png')
    return JsonResponse({
        'name': 'MedAccess Médico - Minha agenda',
        'short_name': 'Minha agenda',
        'description': 'Pacientes da agenda do médico, chegada e atendimento.',
        'id': '/medico/',
        'start_url': '/medico/?origem=pwa',
        'scope': '/medico/',
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0b1f24',
        'theme_color': '#139e86',
        'lang': 'pt-BR',
        'icons': [
            {'src': icone, 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Pacientes de hoje', 'url': '/medico/', 'icons': [{'src': icone, 'sizes': '192x192'}]},
        ],
    }, content_type='application/manifest+json')
