from datetime import datetime, timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Count, F, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from contas.crud import Crud
from contas.models import Clinica
from contas.permissoes import acesso, tem_permissao

from . import services
from .forms import (AvaliacaoForm, ConcluirForm, ConfigForm, ConsultarForm, EncaminharForm, ManifestacaoEditarForm,
                    ManifestacaoForm, MensagemPublicaForm, MotivoForm, ProrrogarForm, PublicoForm, RespostaForm,
                    SetorForm, TextoForm)
from .models import STATUS_ABERTOS, Manifestacao, Setor
from .services import ErroOuvidoria

MAX_PUBLICAS_SESSAO = 5          # por dia, por navegador
MAX_PUBLICAS_HORA = 60           # por clínica (contém robôs que trocam de sessão)
MAX_CONSULTAS = 10               # tentativas de protocolo + chave a cada 15 min


class SetorCrud(Crud):
    model, form_class = Setor, SetorForm
    modulo = 'ouvidoria'
    nome, nome_plural, url, icone = 'Setor', 'Setores da ouvidoria', 'ouvidoria:setor', 'bi-diagram-3'
    colunas = [('nome', 'Setor'), ('responsavel', 'Responsável'), ('publico', 'No formulário público'),
               ('ativo', 'Ativo')]
    busca = ['nome']
    url_sucesso = 'ouvidoria:configurar'


def _pode_editar(request):
    return tem_permissao(request, 'ouvidoria', 'editar')


def _manifestacao(request, pk):
    return get_object_or_404(services.visiveis(request).select_related(
        'setor', 'medico', 'paciente', 'responsavel', 'registrada_por', 'agendamento'), pk=pk)


@never_cache
@acesso(None)
def painel(request):
    c = request.clinica
    modulo = tem_permissao(request, 'ouvidoria')
    hoje = timezone.localdate()
    qs = services.visiveis(request).select_related('setor', 'responsavel', 'paciente')
    aba = request.GET.get('aba', 'abertas')
    if not modulo:
        aba = 'minhas' if aba not in ('minhas', 'todas') else aba
    filtros = {
        'abertas': Q(status__in=STATUS_ABERTOS),
        'vencidas': Q(status__in=STATUS_ABERTOS, prazo__lt=hoje),
        'minhas': Q(status__in=STATUS_ABERTOS, responsavel=request.user),
        'respondidas': Q(status='respondida'),
        'encerradas': Q(status__in=('concluida', 'arquivada')),
    }
    if aba in filtros:
        qs = qs.filter(filtros[aba])
    for campo in ('tipo', 'setor', 'canal'):
        if request.GET.get(campo):
            qs = qs.filter(**{campo: request.GET[campo]})
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(protocolo__icontains=q) | Q(assunto__icontains=q) | Q(nome__icontains=q)
                       | Q(paciente__nome__icontains=q))
    qs = qs.order_by('prazo', 'prioridade', 'id') if aba in ('abertas', 'vencidas', 'minhas') else qs
    ctx = {'manifestacoes': qs[:300], 'aba': aba, 'modulo': modulo, 'pode_editar': _pode_editar(request), 'q': q,
           'tipos': Manifestacao.TIPOS, 'canais': Manifestacao.CANAIS,
           'setores': Setor.objects.filter(clinica=c), 'sel': request.GET}
    if modulo:
        base = Manifestacao.objects.filter(clinica=c)
        abertas = base.filter(status__in=STATUS_ABERTOS)
        ini_mes = timezone.make_aware(datetime.combine(hoje.replace(day=1), datetime.min.time()))
        respondidas = base.filter(primeira_resposta_em__isnull=False, criado_em__gte=ini_mes - timedelta(days=60))
        tempo = respondidas.aggregate(t=Avg(F('primeira_resposta_em') - F('criado_em')))['t']
        no_prazo = respondidas.filter(primeira_resposta_em__date__lte=F('prazo')).count()
        ctx['k'] = {
            'abertas': abertas.count(),
            'vencidas': abertas.filter(prazo__lt=hoje).count(),
            'vencendo': abertas.filter(prazo__gte=hoje, prazo__lte=hoje + timedelta(days=2)).count(),
            'mes': base.filter(criado_em__gte=ini_mes).count(),
            'tempo': round(tempo.total_seconds() / 86400, 1) if tempo else None,
            'no_prazo': round(no_prazo * 100 / respondidas.count()) if respondidas.exists() else None,
            'satisfacao': base.aggregate(m=Avg('avaliacao_nota'))['m'],
            'minhas': abertas.filter(responsavel=request.user).count(),
        }
        ctx['por_tipo'] = list(abertas.values('tipo').annotate(n=Count('id')).order_by('-n'))
        nomes = dict(Manifestacao.TIPOS)
        for r in ctx['por_tipo']:
            r['nome'] = nomes.get(r['tipo'], r['tipo'])
    return render(request, 'ouvidoria/painel.html', ctx)


@acesso(None)
def nova(request):
    services.garantir_config(request.clinica)
    form = ManifestacaoForm(request.POST or None, clinica=request.clinica,
                            initial={'paciente': request.GET.get('paciente')})
    if request.method == 'POST' and form.is_valid():
        d = dict(form.cleaned_data)
        m, chave = services.registrar(request.clinica, usuario=request.user, **d)
        request.session['ouvidoria_chave'] = {'pk': m.pk, 'chave': chave}
        messages.success(request, f'Manifestação registrada. Protocolo {m.protocolo}.')
        return redirect('ouvidoria:comprovante', m.pk)
    return render(request, 'ouvidoria/nova.html', {'form': form})


@never_cache
@acesso(None)
def comprovante(request, pk):
    qs = Manifestacao.objects.filter(clinica=request.clinica)
    if not tem_permissao(request, 'ouvidoria'):
        qs = qs.filter(registrada_por=request.user)
    m = get_object_or_404(qs, pk=pk)
    dado = request.session.get('ouvidoria_chave') or {}
    chave = dado.get('chave') if dado.get('pk') == m.pk else None
    return render(request, 'ouvidoria/comprovante.html', {
        'm': m, 'chave': chave, 'link': services.link_publico(m), 'modulo': tem_permissao(request, 'ouvidoria')})


@never_cache
@acesso(None)
def detalhe(request, pk):
    m = _manifestacao(request, pk)
    editar = _pode_editar(request)
    designado = m.responsavel_id == request.user.pk or m.andamentos.filter(destino=request.user).exists()
    ver_identidade = editar or not m.sigilosa
    andamentos = m.andamentos.select_related('usuario', 'destino', 'setor')
    if not tem_permissao(request, 'ouvidoria'):   # setor designado: não vê notas internas nem a conversa
        andamentos = andamentos.filter(tipo__in=('registro', 'encaminhamento', 'parecer'))
    ctx = {'m': m, 'andamentos': andamentos, 'editar': editar, 'designado': designado,
           'ver_identidade': ver_identidade, 'pode_parecer': (editar or designado) and not m.encerrada}
    if editar:
        sugestao = m.setor.responsavel_id if m.setor_id else None
        ctx.update({
            'f_resposta': RespostaForm(prefix='resp'),
            'f_nota': TextoForm(prefix='nota'),
            'f_encaminhar': EncaminharForm(prefix='enc', clinica=request.clinica,
                                           initial={'setor': m.setor_id, 'destino': sugestao}),
            'f_prorrogar': ProrrogarForm(prefix='pro', initial={'dias': services.garantir_config(
                request.clinica).prorrogacao_dias}),
            'f_concluir': ConcluirForm(prefix='con', initial={'conclusao': 'registrada' if m.tipo in (
                'elogio', 'sugestao') else ''}),
            'f_motivo': MotivoForm(prefix='mot'),
            'f_editar': ManifestacaoEditarForm(instance=m, clinica=request.clinica, prefix='ed'),
            'historico': Manifestacao.objects.filter(clinica=request.clinica, paciente=m.paciente).exclude(
                pk=m.pk)[:8] if m.paciente_id and ver_identidade else [],
        })
    elif ctx['pode_parecer']:
        ctx['f_parecer'] = TextoForm(prefix='par')
    return render(request, 'ouvidoria/detalhe.html', ctx)


ACOES = {
    # nome: (prefixo do form, classe, precisa editar)
    'nota': ('nota', TextoForm, True),
    'responder': ('resp', RespostaForm, True),
    'encaminhar': ('enc', EncaminharForm, True),
    'prorrogar': ('pro', ProrrogarForm, True),
    'concluir': ('con', ConcluirForm, True),
    'arquivar': ('mot', MotivoForm, True),
    'reabrir': ('mot', MotivoForm, True),
    'parecer': ('par', TextoForm, False),
}


@require_POST
@acesso(None)
def acao(request, pk, nome):
    m = _manifestacao(request, pk)
    if nome == 'classificar':
        if not _pode_editar(request):
            raise PermissionDenied
        form = ManifestacaoEditarForm(request.POST, instance=m, clinica=request.clinica, prefix='ed')
        if form.is_valid():
            form.save()
            messages.success(request, 'Classificação atualizada.')
        else:
            messages.error(request, 'Verifique os dados da classificação.')
        return redirect('ouvidoria:detalhe', m.pk)
    if nome not in ACOES:
        raise PermissionDenied
    prefixo, classe, exige_edicao = ACOES[nome]
    if exige_edicao and not _pode_editar(request):
        raise PermissionDenied
    if nome == 'parecer' and not _pode_editar(request):
        designado = m.responsavel_id == request.user.pk or m.andamentos.filter(destino=request.user).exists()
        if not designado:
            raise PermissionDenied
    kw = {'clinica': request.clinica} if classe is EncaminharForm else {}
    form = classe(request.POST, prefix=prefixo, **kw)
    if not form.is_valid():
        erros = '; '.join(f'{form.fields[c].label if c in form.fields else ""} {", ".join(e)}'.strip()
                          for c, e in form.errors.items())
        messages.error(request, f'Não foi possível concluir: {erros}')
        return redirect('ouvidoria:detalhe', m.pk)
    d, u = form.cleaned_data, request.user
    try:
        if nome == 'nota':
            services.nota(m, u, d['texto'])
        elif nome == 'responder':
            services.responder(m, u, d['texto'], concluir=d['concluir'], conclusao=d['conclusao'])
        elif nome == 'encaminhar':
            services.encaminhar(m, u, d['destino'], d['setor'], d['texto'])
        elif nome == 'prorrogar':
            services.prorrogar(m, u, d['dias'], d['texto'])
        elif nome == 'concluir':
            services.concluir(m, u, d['conclusao'], d['texto'])
        elif nome == 'arquivar':
            services.arquivar(m, u, d['texto'])
        elif nome == 'reabrir':
            services.reabrir(m, u, d['texto'])
        elif nome == 'parecer':
            services.parecer(m, u, d['texto'])
    except ErroOuvidoria as e:
        messages.error(request, str(e))
    else:
        messages.success(request, 'Registrado.')
    return redirect('ouvidoria:detalhe', m.pk)


@acesso('ouvidoria', 'editar')
def configurar(request):
    config = services.garantir_config(request.clinica)
    form = ConfigForm(request.POST or None, instance=config, clinica=request.clinica)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuração salva.')
        return redirect('ouvidoria:configurar')
    caminho = reverse('ouvidoria:publico', args=[request.clinica.codigo_publico])
    from django.conf import settings
    return render(request, 'ouvidoria/configurar.html', {
        'form': form, 'config': config, 'setores': Setor.objects.filter(clinica=request.clinica)
        .select_related('responsavel'), 'link': settings.SITE_URL.rstrip('/') + caminho, 'caminho': caminho})


# --------------------------------------------------------------------------- páginas públicas (sem login)

def _clinica_publica(codigo):
    c = get_object_or_404(Clinica, codigo_publico=codigo, ativa=True)
    c.ativar_fuso()
    return c, services.garantir_config(c)


def _limite_publico(request, c):
    agora = timezone.now().timestamp()
    enviados = [t for t in request.session.get('ouvidoria_envios', []) if t > agora - 86400]
    hora = Manifestacao.objects.filter(clinica=c, canal__in=('site', 'app'),
                                       criado_em__gte=timezone.now() - timedelta(hours=1)).count()
    return enviados, len(enviados) >= MAX_PUBLICAS_SESSAO or hora >= MAX_PUBLICAS_HORA


def publico(request, codigo):
    c, config = _clinica_publica(codigo)
    if not config.formulario_publico:
        return render(request, 'ouvidoria/publico/form.html', {'c': c, 'config': config, 'fechado': True})
    form = PublicoForm(request.POST or None, clinica=c, config=config)
    if request.method == 'POST' and form.is_valid():
        d = dict(form.cleaned_data)
        if d.pop('site'):
            return redirect(request.path)
        enviados, bloqueado = _limite_publico(request, c)
        if bloqueado:
            form.add_error(None, 'Muitas manifestações enviadas. Tente novamente mais tarde ou fale com a clínica.')
        else:
            d.pop('lgpd')
            m, chave = services.registrar(c, canal='site', **d)
            request.session['ouvidoria_envios'] = enviados + [timezone.now().timestamp()]
            request.session['ouvidoria_registrada'] = {'pk': m.pk, 'chave': chave}
            return redirect('ouvidoria:registrada', codigo)
    return render(request, 'ouvidoria/publico/form.html', {'c': c, 'config': config, 'form': form})


@never_cache
def registrada(request, codigo):
    c, _ = _clinica_publica(codigo)
    dado = request.session.pop('ouvidoria_registrada', None)
    if not dado:
        return redirect('ouvidoria:consultar', codigo)
    m = get_object_or_404(Manifestacao, pk=dado['pk'], clinica=c)
    return render(request, 'ouvidoria/publico/registrada.html', {'c': c, 'm': m, 'chave': dado['chave'],
                                                                 'link': services.link_publico(m)})


def consultar(request, codigo):
    c, config = _clinica_publica(codigo)
    form = ConsultarForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        agora = timezone.now().timestamp()
        tentativas = [t for t in request.session.get('ouvidoria_consultas', []) if t > agora - 900]
        if len(tentativas) >= MAX_CONSULTAS:
            form.add_error(None, 'Muitas tentativas. Aguarde 15 minutos.')
        else:
            request.session['ouvidoria_consultas'] = tentativas + [agora]
            m = Manifestacao.objects.filter(clinica=c, protocolo=form.cleaned_data['protocolo'].strip()).first()
            if m and m.chave_hash == services.hash_chave(form.cleaned_data['chave']):
                return redirect('ouvidoria:acompanhar', m.token)
            form.add_error(None, 'Protocolo ou chave de acesso não conferem.')
    return render(request, 'ouvidoria/publico/consultar.html', {'c': c, 'config': config, 'form': form})


@never_cache
def acompanhar(request, token):
    m = get_object_or_404(Manifestacao.objects.select_related('clinica', 'setor'), token=token)
    c = m.clinica
    c.ativar_fuso()
    f_msg = MensagemPublicaForm(request.POST if request.POST.get('acao') == 'mensagem' else None)
    f_aval = AvaliacaoForm(request.POST if request.POST.get('acao') == 'avaliar' else None)
    if request.method == 'POST':
        form = f_msg if request.POST.get('acao') == 'mensagem' else f_aval
        if form.is_valid():
            try:
                if form is f_msg:
                    recentes = m.andamentos.filter(tipo='manifestante',
                                                   criado_em__gte=timezone.now() - timedelta(days=1)).count()
                    if recentes >= 5:
                        raise ErroOuvidoria('Limite de mensagens por dia atingido.')
                    services.mensagem_manifestante(m, form.cleaned_data['texto'])
                    messages.success(request, 'Mensagem enviada à ouvidoria.')
                else:
                    d = form.cleaned_data
                    services.avaliar(m, d['resolvida'], d['nota'], d['comentario'])
                    messages.success(request, 'Obrigado pela avaliação!')
            except ErroOuvidoria as e:
                messages.error(request, str(e))
            return redirect('ouvidoria:acompanhar', token)
    resp = render(request, 'ouvidoria/publico/acompanhar.html', {
        'c': c, 'm': m, 'andamentos': m.andamentos.filter(publico=True),
        'f_msg': f_msg if m.status != 'arquivada' else None,
        'f_aval': f_aval if m.status in ('respondida', 'concluida') and not m.avaliada_em
        and m.andamentos.filter(tipo='resposta').exists() else None})
    resp['Cache-Control'] = 'private, no-store'
    resp['X-Robots-Tag'] = 'noindex'
    return resp
