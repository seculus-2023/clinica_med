"""App do paciente (PWA): acesso com CPF + data de nascimento + código enviado ao WhatsApp/e-mail cadastrado.

Só entra quem tem "acesso ao app" liberado no cadastro. O paciente confirma, cancela e marca consultas, avisa a
clínica e vê medicações prescritas, medições (sinais vitais e exames), documentos liberados e pagamentos.
Não há acesso a anotações clínicas do prontuário.
"""
import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_POST

from agenda.models import Agendamento
from cadastros.models import Medico, Paciente
from contas.crud import FormSimples
from contas.models import Clinica, Lembrete

from .models import AvisoPaciente

SESSAO = 'portal'
VALIDADE_CODIGO_MIN = 10
MAX_TENTATIVAS = 5
MAX_ENVIOS = 3
MAX_AVISOS_DIA = 10


def _digitos(s):
    return ''.join(c for c in str(s or '') if c.isdigit())


def _hash(codigo):
    return hashlib.sha256(codigo.encode()).hexdigest()


def _clinica(codigo):
    c = get_object_or_404(Clinica, codigo_publico=codigo, ativa=True)
    c.ativar_fuso()
    return c


def paciente_logado(view):
    @wraps(view)
    def wrapper(request, codigo, *args, **kwargs):
        c = _clinica(codigo)
        s = request.session.get(SESSAO) or {}
        if s.get('clinica') != c.pk or not s.get('paciente') or s.get('expira', 0) < timezone.now().timestamp():
            request.session.pop(SESSAO, None)
            return redirect('portal:entrar', codigo)
        p = Paciente.objects.filter(pk=s['paciente'], clinica=c, ativo=True, acesso_app=True).first()
        if not p:   # acesso revogado vale imediatamente
            request.session.pop(SESSAO, None)
            return redirect('portal:entrar', codigo)
        s['expira'] = (timezone.now() + timedelta(hours=1)).timestamp()   # sessão de 1h, renovada a cada acesso
        request.session[SESSAO] = s
        if not p.consentimento_lgpd_em and view.__name__ != 'termo':
            return redirect('portal:termo', codigo)
        resp = view(request, c, p, *args, **kwargs)
        resp['Cache-Control'] = 'private, no-store'   # dados de saúde não ficam no cache do aparelho
        return resp
    return wrapper


class EntrarForm(FormSimples):
    cpf = forms.CharField(label='CPF', max_length=14)
    nascimento = forms.DateField(label='Data de nascimento')


class CodigoForm(FormSimples):
    codigo = forms.CharField(label='Código recebido', max_length=6,
                             widget=forms.TextInput(attrs={'inputmode': 'numeric', 'autocomplete': 'one-time-code'}))


def _mascarar(tel, email):
    destinos = []
    d = _digitos(tel)
    if d:
        destinos.append(f'WhatsApp terminado em {d[-4:]}')
    if email and '@' in email:
        u, dom = email.split('@', 1)
        destinos.append(f'e-mail {u[:2]}***@{dom}')
    return ' e '.join(destinos)


def _codigos_recentes(c, p):
    """Códigos enviados ao paciente em 15 min; vale entre aparelhos e sessões, ao contrário do limite da sessão."""
    from notificacoes.models import Notificacao
    from notificacoes.services import normalizar_telefone
    destinos = [d for d in (normalizar_telefone(p.celular) if p.celular else '', p.email) if d]
    por_canal = Notificacao.objects.filter(clinica=c, evento='portal_codigo', destinatario__in=destinos,
                                           criado_em__gte=timezone.now() - timedelta(minutes=15)
                                           ).values('canal').annotate(n=Count('pk'))
    return max((x['n'] for x in por_canal), default=0)


def entrar(request, codigo):
    c = _clinica(codigo)
    s = request.session.get(SESSAO) or {}
    if request.method == 'GET' and s.get('clinica') == c.pk and s.get('expira', 0) > timezone.now().timestamp():
        return redirect('portal:inicio', codigo)
    etapa = request.session.get('portal_login') or {}
    if etapa.get('clinica') != c.pk:
        etapa = {}
    form, form_codigo = EntrarForm(request.POST or None), CodigoForm(request.POST or None)
    if request.method == 'POST' and request.POST.get('etapa') == 'dados' and form.is_valid():
        envios = [t for t in etapa.get('envios', []) if t > (timezone.now() - timedelta(minutes=15)).timestamp()]
        if len(envios) >= MAX_ENVIOS:
            messages.error(request, 'Muitas solicitações. Aguarde 15 minutos e tente novamente.')
            return redirect('portal:entrar', codigo)
        cpf = _digitos(form.cleaned_data['cpf'])
        p = next((x for x in Paciente.objects.filter(clinica=c, ativo=True, acesso_app=True,
                                                     data_nascimento=form.cleaned_data['nascimento'])
                  if _digitos(x.cpf) == cpf and len(cpf) == 11), None)
        etapa = {'clinica': c.pk, 'envios': envios + [timezone.now().timestamp()], 'tentativas': 0}
        # mesma resposta para dados errados, sem liberação ou limite atingido: não revela quem é paciente
        if p and (p.celular or p.email) and _codigos_recentes(c, p) < MAX_ENVIOS:
            cod = f'{secrets.randbelow(10 ** 6):06d}'
            etapa.update({'paciente': p.pk, 'hash': _hash(cod),
                          'expira': (timezone.now() + timedelta(minutes=VALIDADE_CODIGO_MIN)).timestamp(),
                          'destino': _mascarar(p.celular, p.email)})
            from notificacoes.services import enfileirar
            enfileirar(c, p.nome, telefone=p.celular, email=p.email, assunto='Código de acesso ao portal',
                       mensagem=f'{c.nome}: seu código de acesso ao portal do paciente é {cod}. Válido por '
                                f'{VALIDADE_CODIGO_MIN} minutos. Não compartilhe este código.',
                       evento='portal_codigo', sms=True)
        else:
            etapa.update({'paciente': None, 'hash': _hash(secrets.token_hex(8)),
                          'expira': (timezone.now() + timedelta(minutes=VALIDADE_CODIGO_MIN)).timestamp(),
                          'destino': 'o contato cadastrado'})
        request.session['portal_login'] = etapa
        return redirect('portal:entrar', codigo)
    if request.method == 'POST' and request.POST.get('etapa') == 'codigo' and etapa and form_codigo.is_valid():
        etapa['tentativas'] = etapa.get('tentativas', 0) + 1
        valido = (etapa.get('paciente') and etapa['expira'] > timezone.now().timestamp()
                  and etapa['tentativas'] <= MAX_TENTATIVAS
                  and secrets.compare_digest(_hash(_digitos(form_codigo.cleaned_data['codigo'])), etapa['hash']))
        if valido:
            request.session.cycle_key()
            request.session.pop('portal_login', None)
            request.session[SESSAO] = {'clinica': c.pk, 'paciente': etapa['paciente'],
                                       'expira': (timezone.now() + timedelta(hours=1)).timestamp()}
            return redirect('portal:inicio', codigo)
        request.session['portal_login'] = etapa
        if etapa['tentativas'] >= MAX_TENTATIVAS:
            request.session.pop('portal_login', None)
            messages.error(request, 'Número de tentativas excedido. Solicite um novo código.')
        else:
            messages.error(request, 'Código inválido ou expirado.')
        return redirect('portal:entrar', codigo)
    if request.GET.get('reiniciar'):
        request.session.pop('portal_login', None)
        return redirect('portal:entrar', codigo)
    return render(request, 'portal/entrar.html', {'c': c, 'form': form, 'form_codigo': form_codigo,
                                                  'aguardando': bool(etapa.get('hash')), 'destino': etapa.get('destino')})


@require_POST
def sair(request, codigo):
    request.session.pop(SESSAO, None)
    return redirect('portal:entrar', codigo)


def manifest(request, codigo):
    c = _clinica(codigo)
    base = reverse('portal:inicio', args=[codigo])
    return JsonResponse({
        'name': f'{c.nome} - App do paciente',
        'short_name': 'Paciente',
        'description': 'Consultas, medicações, medições e avisos para a clínica.',
        'id': base,
        'start_url': f'{base}?origem=pwa',
        'scope': base,
        'display': 'standalone',
        'orientation': 'portrait',
        'background_color': '#0b1f24',
        'theme_color': '#139e86',
        'lang': 'pt-BR',
        'icons': [
            {'src': static('icons/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
    }, content_type='application/manifest+json')


class TermoForm(FormSimples):
    aceito = forms.BooleanField(label='Li e aceito')


@paciente_logado
def termo(request, c, p):
    from agenda.publico import TEXTO_LGPD
    if p.consentimento_lgpd_em:
        return redirect('portal:inicio', c.codigo_publico)
    form = TermoForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        p.consentimento_lgpd_em = timezone.now()
        p.save(update_fields=['consentimento_lgpd_em'])
        return redirect('portal:inicio', c.codigo_publico)
    return render(request, 'portal/termo.html', {'c': c, 'p': p, 'form': form, 'texto': TEXTO_LGPD})


@paciente_logado
def inicio(request, c, p):
    agora = timezone.now()
    return render(request, 'portal/inicio.html', {
        'c': c, 'p': p, 'aba': 'inicio', 'agora': agora,
        'proximos': Agendamento.objects.filter(paciente=p, inicio__gte=agora - timedelta(hours=2)).exclude(
            status__in=('cancelado', 'concluido', 'faltou')).select_related('medico', 'tipo').order_by('inicio')[:10],
    })


def _consulta(c, p, pk):
    return get_object_or_404(Agendamento.objects.select_related('medico', 'tipo'), pk=pk, clinica=c, paciente=p)


@require_POST
@paciente_logado
def confirmar(request, c, p, pk):
    from agenda.services import mudar_status
    ag = _consulta(c, p, pk)
    if ag.status == 'agendado' and ag.inicio > timezone.now():
        mudar_status(ag, 'confirmado', origem='paciente')
        messages.success(request, 'Consulta confirmada.')
    else:
        messages.error(request, 'Esta consulta não pode mais ser confirmada.')
    return redirect('portal:inicio', c.codigo_publico)


@require_POST
@paciente_logado
def cancelar(request, c, p, pk):
    from agenda.services import mudar_status
    ag = _consulta(c, p, pk)
    if ag.status in ('agendado', 'confirmado') and ag.inicio > timezone.now():
        mudar_status(ag, 'cancelado', origem='paciente')
        Lembrete.objects.create(clinica=c, origem='sistema', titulo=f'Paciente cancelou: {p}'[:150],
                                mensagem=f'{ag} cancelado pelo paciente no app.',
                                link=reverse('agenda:detalhe', args=[ag.pk]))
        messages.success(request, 'Consulta cancelada.')
    else:
        messages.error(request, 'Esta consulta não pode mais ser cancelada pelo app. Fale com a clínica.')
    return redirect('portal:inicio', c.codigo_publico)


def _ler_slot(texto):
    try:
        slot = parse_datetime(texto or '')
    except ValueError:
        return None
    if not slot:
        return None
    return timezone.localtime(slot) if timezone.is_aware(slot) else timezone.make_aware(slot)


@paciente_logado
def agendar(request, c, p):
    from agenda import marcacao
    from agenda.disponibilidade import horarios_livres
    if not c.agendamento_online:
        return render(request, 'portal/agendar.html', {'c': c, 'p': p, 'aba': 'agendar', 'fechado': True})
    ctx = marcacao.contexto(c, request.GET, publico=True)
    tipo, medico = ctx['tipo'], ctx['medico']
    slot = _ler_slot(request.POST.get('slot') or request.GET.get('slot'))
    erro = ''
    if request.method == 'POST' and tipo and medico and slot:
        fim = slot + timedelta(minutes=tipo.duracao_minutos or 30)
        with transaction.atomic():
            Medico.objects.select_for_update().get(pk=medico.pk)   # evita dois pacientes no mesmo horário
            no_prazo = (slot.date() - timezone.localdate()).days <= c.online_dias
            if not no_prazo or slot not in horarios_livres(c, medico, tipo, slot.date()):
                erro = 'Este horário não está mais disponível. Escolha outro.'
            elif Agendamento.objects.filter(clinica=c, paciente=p, inicio__lt=fim, fim__gt=slot).exclude(
                    status__in=('cancelado', 'faltou')).exists():
                erro = 'Você já tem outra consulta neste horário.'
            else:
                ag = Agendamento.objects.create(clinica=c, paciente=p, medico=medico, tipo=tipo, inicio=slot,
                                                origem='online', notificar=True)
                Lembrete.objects.create(clinica=c, origem='online',
                                        titulo=f'App do paciente: {p} - {slot:%d/%m %H:%M}'[:150],
                                        mensagem=f'{tipo} com {medico}', link=reverse('agenda:detalhe', args=[ag.pk]))
        if not erro:
            messages.success(request, f'Consulta marcada para {slot:%d/%m/%Y} às {slot:%H:%M}.')
            return redirect('portal:inicio', c.codigo_publico)
    ctx.update({'c': c, 'p': p, 'aba': 'agendar', 'slot': slot, 'erro': erro})
    return render(request, 'portal/agendar.html', ctx)


@paciente_logado
def medicacoes(request, c, p):
    from documentos.models import Documento
    receitas = (Documento.objects.filter(clinica=c, paciente=p, visivel_paciente=True,
                                         tipo__in=('receita', 'receita_especial'))
                .select_related('medico').prefetch_related('itens__medicamento')[:30])
    return render(request, 'portal/medicacoes.html', {'c': c, 'p': p, 'aba': 'medicacoes', 'receitas': receitas})


@paciente_logado
def medicoes(request, c, p):
    from prontuario.models import Atendimento, ResultadoExame
    # só os campos de medição: evolução e anotações do prontuário não são carregadas
    campos = ('data', 'pa_sistolica', 'pa_diastolica', 'fc', 'fr', 'temperatura', 'spo2', 'peso', 'altura',
              'glicemia', 'dor')
    atendimentos = Atendimento.objects.filter(clinica=c, paciente=p, status='finalizado').only(*campos)[:60]
    return render(request, 'portal/medicoes.html', {
        'c': c, 'p': p, 'aba': 'medicoes',
        'sinais': [a for a in atendimentos if a.tem_sinais_vitais],
        'resultados': ResultadoExame.objects.filter(paciente=p).select_related('exame').order_by('-data',
                                                                                                 'exame__nome')[:60],
    })


class AvisoForm(FormSimples):
    tipo = forms.ChoiceField(label='Sobre o que é o aviso?', choices=AvisoPaciente.TIPOS)
    agendamento = forms.ModelChoiceField(label='Consulta relacionada', queryset=Agendamento.objects.none(),
                                         required=False, empty_label='Nenhuma')
    mensagem = forms.CharField(label='Mensagem', max_length=500, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, paciente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['agendamento'].queryset = Agendamento.objects.filter(
            paciente=paciente, inicio__gte=timezone.now(), status__in=('agendado', 'confirmado')).order_by('inicio')
        self.fields['agendamento'].label_from_instance = (
            lambda a: f'{timezone.localtime(a.inicio):%d/%m/%Y %H:%M} - {a.tipo}')


def _mensagens_da_clinica(c, p):
    """Mensagens enviadas ao paciente, uma por evento (a mesma sai em WhatsApp, e-mail e SMS)."""
    from notificacoes.models import Notificacao
    vistos, lista = set(), []
    for n in (Notificacao.objects.filter(clinica=c, agendamento__paciente=p).exclude(status='erro')
              .exclude(evento='portal_codigo').order_by('-criado_em')[:60]):
        chave = (n.agendamento_id, n.evento)
        if chave not in vistos:
            vistos.add(chave)
            lista.append(n)
    return lista[:20]


@paciente_logado
def avisos(request, c, p):
    form = AvisoForm(request.POST or None, paciente=p)
    if request.method == 'POST' and form.is_valid():
        hoje = AvisoPaciente.objects.filter(paciente=p, criado_em__gte=timezone.now() - timedelta(days=1)).count()
        if hoje >= MAX_AVISOS_DIA:
            messages.error(request, 'Limite de avisos atingido. Entre em contato com a clínica por telefone.')
            return redirect('portal:avisos', c.codigo_publico)
        d = form.cleaned_data
        aviso = AvisoPaciente.objects.create(clinica=c, paciente=p, agendamento=d['agendamento'], tipo=d['tipo'],
                                             mensagem=d['mensagem'])
        link = (reverse('agenda:detalhe', args=[aviso.agendamento_id]) if aviso.agendamento_id
                else reverse('cadastros:paciente_ficha', args=[p.pk]))
        Lembrete.objects.create(clinica=c, origem='app_paciente',
                                titulo=f'Aviso do paciente: {aviso.get_tipo_display()} - {p}'[:150],
                                mensagem=aviso.mensagem, link=link)
        messages.success(request, 'Aviso enviado para a clínica.')
        return redirect('portal:avisos', c.codigo_publico)
    return render(request, 'portal/avisos.html', {
        'c': c, 'p': p, 'aba': 'avisos', 'form': form,
        'enviados': AvisoPaciente.objects.filter(paciente=p).select_related('agendamento')[:20],
        'recebidos': _mensagens_da_clinica(c, p),
    })


@paciente_logado
def ouvidoria(request, c, p):
    from ouvidoria import services as ouv
    from ouvidoria.forms import PublicoForm
    from ouvidoria.models import Manifestacao
    config = ouv.garantir_config(c)
    form = PublicoForm(request.POST or None, clinica=c, config=config, paciente=p)
    if request.method == 'POST' and form.is_valid():
        d = dict(form.cleaned_data)
        d.pop('site', None)
        if Manifestacao.objects.filter(paciente=p, criado_em__gte=timezone.now() - timedelta(days=1)).count() >= 5:
            messages.error(request, 'Limite diário de manifestações atingido. Fale com a clínica por telefone.')
            return redirect('portal:ouvidoria', c.codigo_publico)
        m, _ = ouv.registrar(c, canal='app', paciente=p, relacao='paciente', **d)
        messages.success(request, f'Manifestação registrada. Protocolo {m.protocolo}, resposta até '
                                  f'{m.prazo:%d/%m/%Y}.')
        return redirect('portal:ouvidoria', c.codigo_publico)
    return render(request, 'portal/ouvidoria.html', {
        'c': c, 'p': p, 'aba': 'mais', 'form': form, 'config': config,
        'manifestacoes': Manifestacao.objects.filter(clinica=c, paciente=p, anonima=False)[:20]})


@paciente_logado
def mais(request, c, p):
    from documentos.models import Documento, DocumentoAssinado
    from financeiro.models import Lancamento
    from prontuario.models import Anexo
    return render(request, 'portal/mais.html', {
        'c': c, 'p': p, 'aba': 'mais',
        'historico': Agendamento.objects.filter(paciente=p, inicio__lt=timezone.now(), status='concluido')
        .select_related('medico', 'tipo').order_by('-inicio')[:20],
        'documentos': Documento.objects.filter(paciente=p, visivel_paciente=True).select_related('medico')[:30],
        'assinados': DocumentoAssinado.objects.filter(paciente=p).select_related('medico')[:30],
        'exames': Anexo.objects.filter(paciente=p, visivel_paciente=True)[:30],
        'recibos': Lancamento.objects.filter(paciente=p, tipo='receita', status='pago').order_by('-data_pagamento')[:20],
        'pendentes': Lancamento.objects.filter(paciente=p, tipo='receita', status='pendente').order_by('vencimento')[:20],
    })


@paciente_logado
def documento(request, c, p, pk):
    from documentos.models import Documento, url_verificacao
    doc = get_object_or_404(Documento.objects.select_related('medico', 'clinica'), pk=pk, paciente=p,
                            visivel_paciente=True)
    return render(request, 'documentos/imprimir.html', {'doc': doc, 'c': c, 'assinar': False,
                                                        'url_verificacao': url_verificacao(doc.codigo_verificacao)})


def _arquivo(f, nome, tipo):
    resp = FileResponse(f.open('rb'), content_type=tipo)
    resp['Content-Disposition'] = f'inline; filename="{nome}"'
    resp['Cache-Control'] = 'private, no-store'
    return resp


@paciente_logado
def assinado(request, c, p, pk):
    from documentos.models import DocumentoAssinado
    d = get_object_or_404(DocumentoAssinado, pk=pk, paciente=p)
    return _arquivo(d.arquivo, d.arquivo.name.split('/')[-1], 'application/pdf')


@paciente_logado
def exame(request, c, p, pk):
    import mimetypes
    from prontuario.models import Anexo
    x = get_object_or_404(Anexo, pk=pk, paciente=p, visivel_paciente=True)
    if not x.arquivo:
        raise Http404
    return _arquivo(x.arquivo, x.nome_arquivo, mimetypes.guess_type(x.nome_arquivo)[0] or 'application/octet-stream')


@paciente_logado
def recibo(request, c, p, pk):
    from financeiro.extenso import por_extenso
    from financeiro.models import FORMAS_PAGAMENTO, Lancamento
    lan = get_object_or_404(Lancamento, pk=pk, paciente=p, tipo='receita', status='pago')
    valor = lan.valor_pago or lan.valor
    return render(request, 'financeiro/recibo.html', {'lan': lan, 'c': c, 'valor': valor, 'extenso': por_extenso(valor),
                                                      'forma': dict(FORMAS_PAGAMENTO).get(lan.forma_pagamento, '')})
