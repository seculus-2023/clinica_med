import uuid

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from agenda.models import Agendamento
from contas.crud import Crud
from contas.permissoes import acesso, medico_restrito, tem_permissao

from . import services
from .forms import ConfigPainelForm, PontoForm, ServicoForm
from .models import ConfigPainel, PontoAtendimento, Senha, ServicoSenha
from .services import ErroSenha


def _senha(request, pk):
    return get_object_or_404(Senha, pk=pk, clinica=request.clinica)


def _agendamento(request, pk):
    qs = Agendamento.objects.select_related('clinica', 'paciente', 'medico', 'recurso', 'tipo')
    med = medico_restrito(request)
    if med:
        qs = qs.filter(medico=med)
    return get_object_or_404(qs, pk=pk, clinica=request.clinica)


def _voltar(request):
    prox = request.POST.get('next', '')
    if prox and url_has_allowed_host_and_scheme(prox, {request.get_host()}, request.is_secure()):
        return redirect(prox)
    return redirect('senhas:painel')


@never_cache
@acesso('agenda')
def painel(request):
    config = services.garantir_padroes(request.clinica)
    data = services.hoje(request.clinica)
    ponto = services.guiche_do_usuario(request.clinica, request.user)
    do_dia = Senha.objects.filter(clinica=request.clinica, data=data)
    fila = list(do_dia.filter(status='aguardando').select_related('servico', 'paciente')
                .order_by('-preferencial', 'criado_em', 'id'))
    atual = None
    if ponto:
        atual = do_dia.filter(ponto=ponto, status__in=services.STATUS_ATIVOS).select_related('servico',
                                                                                              'paciente').first()
    pode_editar = tem_permissao(request, 'agenda', 'editar')
    ctx = {
        'fila': fila,
        'ponto': ponto,
        'pode_editar': pode_editar,
        'pode_chamar': pode_editar and ponto is not None and atual is None,
        'guiches': services.situacao_guiches(request.clinica, request.user),
        'n_preferencial': sum(1 for s in fila if s.preferencial),
        'em_curso': do_dia.filter(status__in=services.STATUS_ATIVOS).select_related('servico', 'ponto', 'chamada_por')
                          .order_by('-chamada_em'),
        'atendidas': do_dia.filter(status='concluida').count(),
        'ausentes': do_dia.filter(status='ausente').select_related('servico').order_by('-fim_em')[:8],
    }
    if request.GET.get('parcial') == '1':
        return render(request, 'senhas/_fila.html', ctx)
    emitida = None
    if str(request.GET.get('emitida', '')).isdigit():
        emitida = do_dia.filter(pk=request.GET['emitida']).first()
    ctx.update({'config': config, 'atual': atual, 'emitida': emitida,
                'servicos': ServicoSenha.objects.filter(clinica=request.clinica, ativo=True)})
    return render(request, 'senhas/painel.html', ctx)


@require_POST
@acesso('agenda', 'editar')
def assumir_guiche(request, pk):
    ponto = get_object_or_404(PontoAtendimento, pk=pk, clinica=request.clinica)
    try:
        ponto = services.assumir_guiche(request.clinica, ponto, request.user)
        messages.success(request, f'Você está atendendo em {ponto.nome}.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@require_POST
@acesso('agenda', 'editar')
def sair_guiche(request):
    try:
        ponto = services.sair_guiche(request.clinica, request.user)
        messages.success(request, f'{ponto.nome} foi liberado.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@require_POST
@acesso('agenda', 'editar')
def liberar_guiche(request, pk):
    ponto = get_object_or_404(PontoAtendimento, pk=pk, clinica=request.clinica)
    try:
        services.liberar_guiche(request.clinica, ponto, request.user)
        messages.success(request, f'{ponto.nome} foi liberado.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@require_POST
@acesso('agenda', 'editar')
def emitir(request):
    servico = get_object_or_404(ServicoSenha, pk=request.POST.get('servico') or 0, clinica=request.clinica, ativo=True)
    senha = services.emitir(request.clinica, servico, request.POST.get('preferencial') == '1', usuario=request.user)
    return redirect(f"{reverse('senhas:painel')}?emitida={senha.pk}")


@require_POST
@acesso('agenda', 'editar')
def chamar(request, pk=None):
    ponto = services.guiche_do_usuario(request.clinica, request.user)
    if ponto is None:
        messages.error(request, 'Assuma um guichê para chamar senhas.')
        return redirect('senhas:painel')
    try:
        senha = services.chamar_proxima(request.clinica, ponto, request.user, pk)
        messages.success(request, f'Senha {senha.codigo} chamada em {ponto.nome}.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@require_POST
@acesso('agenda', 'editar')
def rechamar(request, pk):
    try:
        senha = services.rechamar(_senha(request, pk), request.user)
        messages.success(request, f'Senha {senha.codigo} chamada novamente.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@require_POST
@acesso('agenda', 'editar')
def acao(request, pk, nome):
    try:
        senha = services.aplicar_acao(_senha(request, pk), nome, request.user)
        messages.success(request, f'Senha {senha.codigo}: {senha.get_status_display().lower()}.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return redirect('senhas:painel')


@acesso('agenda')
def ticket(request, pk):
    senha = get_object_or_404(Senha.objects.select_related('servico'), pk=pk, clinica=request.clinica)
    return render(request, 'senhas/ticket.html', {'s': senha, 'clinica': request.clinica})


@require_POST
@acesso('agenda', 'editar')
def agendamento_emitir(request, pk):
    ag = _agendamento(request, pk)
    try:
        senha, criada = services.emitir_para_agendamento(ag, request.user)
        messages.success(request, f'{ag.paciente.nome}: senha {senha.codigo}' + ('.' if criada else ' (já emitida).'))
    except ErroSenha as e:
        messages.error(request, str(e))
    return _voltar(request)


@require_POST
@acesso('agenda', 'editar')
def agendamento_chamar(request, pk):
    ag = _agendamento(request, pk)
    try:
        senha = services.chamar_agendamento(ag, request.user)
        messages.success(request, f'Senha {senha.codigo} chamada para {senha.local}.')
    except ErroSenha as e:
        messages.error(request, str(e))
    return _voltar(request)


@acesso('agenda', 'editar')
def configurar(request):
    config = services.garantir_padroes(request.clinica)
    form = ConfigPainelForm(request.POST or None, instance=config, clinica=request.clinica)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Painel atualizado.')
        return redirect('senhas:configurar')
    return render(request, 'senhas/configurar.html', {
        'form': form, 'config': config,
        'link_tv': request.build_absolute_uri(config.caminho_tv),
        'servicos': ServicoSenha.objects.filter(clinica=request.clinica),
        'pontos': PontoAtendimento.objects.filter(clinica=request.clinica).prefetch_related('responsaveis'),
        'gestor': services.e_gestor(request.clinica, request.user),
    })


@require_POST
@acesso('agenda', 'editar')
def novo_link(request):
    config = services.garantir_padroes(request.clinica)
    config.token = uuid.uuid4()
    config.save(update_fields=['token'])
    messages.success(request, 'Novo link gerado. O link anterior parou de funcionar: atualize-o nas TVs.')
    return redirect('senhas:configurar')


# ---- TV (sem login: acesso pelo link secreto; não expõe dados de pacientes) ----

def _config_tv(token):
    config = ConfigPainel.objects.select_related('clinica').filter(token=token, clinica__ativa=True).first()
    if config is None:
        raise Http404
    config.clinica.ativar_fuso()
    return config


@never_cache
def tv(request, token):
    config = _config_tv(token)
    return render(request, 'senhas/tv.html', {'config': config, 'clinica': config.clinica,
                                              'titulo': config.titulo or config.clinica.nome})


@never_cache
def tv_dados(request, token):
    config = _config_tv(token)
    desde = request.GET.get('desde', '')
    return JsonResponse(services.dados_painel(config, int(desde) if desde.isdigit() else None))


class ServicoCrud(Crud):
    model, form_class = ServicoSenha, ServicoForm
    modulo = 'agenda'
    nome, nome_plural, url, icone = 'Serviço de senha', 'Serviços de senha', 'senhas:servico', 'bi-ticket-perforated'
    descricao = 'Filas de atendimento. A letra identifica a senha (A001, C002...).'
    colunas = [('prefixo', 'Letra'), ('nome', 'Nome'), ('ordem', 'Ordem'), ('ativo', 'Ativo')]
    busca = ['nome']
    url_sucesso = 'senhas:configurar'


class PontoCrud(Crud):
    model, form_class = PontoAtendimento, PontoForm
    modulo = 'administrativo'  # quem edita a agenda não pode se autorizar em um guichê
    nome, nome_plural, url, icone = 'Guichê', 'Guichês', 'senhas:ponto', 'bi-door-open'
    descricao = 'Locais de onde as senhas são chamadas e os usuários autorizados em cada um.'
    colunas = [('nome', 'Nome'), ('responsaveis', 'Usuários autorizados'), ('ativo', 'Ativo')]
    busca = ['nome']
    url_sucesso = 'senhas:configurar'
