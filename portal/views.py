"""Portal do paciente: acesso com CPF + data de nascimento + código enviado ao WhatsApp/e-mail cadastrado.

O paciente vê: próximos agendamentos (confirmar/cancelar/check-in/teleconsulta), receitas e atestados liberados,
documentos assinados, exames liberados pela clínica, resultados laboratoriais e recibos de pagamento.
Não há acesso a anotações clínicas do prontuário.
"""
import hashlib
import secrets
from datetime import timedelta
from functools import wraps

from django import forms
from django.contrib import messages
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from cadastros.models import Paciente
from contas.crud import FormSimples
from contas.models import Clinica

SESSAO = 'portal'
VALIDADE_CODIGO_MIN = 10
MAX_TENTATIVAS = 5
MAX_ENVIOS = 3


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
        p = Paciente.objects.filter(pk=s['paciente'], clinica=c, ativo=True).first()
        if not p:
            return redirect('portal:entrar', codigo)
        s['expira'] = (timezone.now() + timedelta(hours=1)).timestamp()   # sessão de 1h, renovada a cada acesso
        request.session[SESSAO] = s
        return view(request, c, p, *args, **kwargs)
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


def entrar(request, codigo):
    c = _clinica(codigo)
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
        p = next((x for x in Paciente.objects.filter(clinica=c, ativo=True,
                                                     data_nascimento=form.cleaned_data['nascimento'])
                  if _digitos(x.cpf) == cpf and len(cpf) == 11), None)
        etapa = {'clinica': c.pk, 'envios': envios + [timezone.now().timestamp()], 'tentativas': 0}
        if p and (p.celular or p.email):
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


def sair(request, codigo):
    request.session.pop(SESSAO, None)
    return redirect('portal:entrar', codigo)


@paciente_logado
def inicio(request, c, p):
    from agenda.models import Agendamento
    from documentos.models import Documento, DocumentoAssinado
    from financeiro.models import Lancamento
    from prontuario.models import Anexo, ResultadoExame
    agora = timezone.now()
    ctx = {
        'c': c, 'p': p,
        'proximos': Agendamento.objects.filter(paciente=p, inicio__gte=agora - timedelta(hours=2)).exclude(
            status__in=('cancelado',)).select_related('medico', 'tipo').order_by('inicio')[:10],
        'historico': Agendamento.objects.filter(paciente=p, inicio__lt=agora, status='concluido').select_related(
            'medico', 'tipo').order_by('-inicio')[:20],
        'documentos': Documento.objects.filter(paciente=p, visivel_paciente=True).select_related('medico')[:30],
        'assinados': DocumentoAssinado.objects.filter(paciente=p).select_related('medico')[:30],
        'exames': Anexo.objects.filter(paciente=p, visivel_paciente=True)[:30],
        'resultados': ResultadoExame.objects.filter(paciente=p).select_related('exame').order_by('-data', 'exame__nome')[:60],
        'recibos': Lancamento.objects.filter(paciente=p, tipo='receita', status='pago').order_by('-data_pagamento')[:20],
        'pendentes': Lancamento.objects.filter(paciente=p, tipo='receita', status='pendente').order_by('vencimento')[:20],
    }
    return render(request, 'portal/inicio.html', ctx)


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
