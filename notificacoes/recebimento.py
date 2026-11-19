"""Recebimento de mensagens do WhatsApp (webhook) e caixa de conversas.

URL do webhook (por clínica): /notificacoes/webhook/<codigo_publico>/<token>/
Formatos aceitos: Evolution API (messages.upsert), Z-API (ReceivedCallback), WhatsApp Cloud API (Meta) e webhook
genérico {"telefone": "...", "mensagem": "..."}. Na Meta, use o mesmo token como "verify token".
"""
import json
import re
import secrets
import unicodedata
from datetime import timedelta

from django.contrib import messages
from django.db.models import Count, Max, Q
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from cadastros.models import Paciente
from contas.models import Clinica, Lembrete
from contas.permissoes import acesso, tem_permissao

from .models import MensagemRecebida, Notificacao
from .services import enfileirar, normalizar_telefone

SIM = {'sim', 's', '1', 'confirmo', 'confirmado', 'ok', 'confirmar', 'sim confirmo', 'pode confirmar', 'vou', 'estarei'}
NAO = {'nao', 'n', '2', 'cancelar', 'cancela', 'cancelo', 'nao vou', 'nao poderei', 'desmarcar'}


def garantir_token(clinica):
    if not clinica.webhook_token:
        clinica.webhook_token = secrets.token_urlsafe(24)
        clinica.save(update_fields=['webhook_token'])
    return clinica.webhook_token


def url_webhook(clinica):
    from django.conf import settings
    return settings.SITE_URL + reverse('notificacoes:webhook', args=[clinica.codigo_publico, garantir_token(clinica)])


def _norm(txt):
    t = unicodedata.normalize('NFKD', txt or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9 ]', '', t).strip()


def extrair(payload):
    """Retorna lista de (telefone, texto, nome, id_externo) das mensagens recebidas (ignora as enviadas por nós)."""
    msgs = []
    if isinstance(payload, dict) and 'entry' in payload:                      # Meta Cloud API
        for e in payload.get('entry', []):
            for ch in e.get('changes', []):
                v = ch.get('value', {})
                nomes = {c.get('wa_id'): (c.get('profile') or {}).get('name', '') for c in v.get('contacts', [])}
                for m in v.get('messages', []):
                    texto = (m.get('text') or {}).get('body') or (m.get('button') or {}).get('text') or \
                        ((m.get('interactive') or {}).get('button_reply') or {}).get('title', '')
                    msgs.append((m.get('from', ''), texto, nomes.get(m.get('from'), ''), m.get('id', '')))
    elif isinstance(payload, dict) and payload.get('event', '').lower().replace('_', '.') == 'messages.upsert':  # Evolution
        dados = payload.get('data') or {}
        for d in (dados if isinstance(dados, list) else [dados]):
            chave = d.get('key') or {}
            if chave.get('fromMe') or '@g.us' in chave.get('remoteJid', ''):
                continue
            m = d.get('message') or {}
            texto = m.get('conversation') or (m.get('extendedTextMessage') or {}).get('text') or \
                (m.get('buttonsResponseMessage') or {}).get('selectedDisplayText', '')
            msgs.append((chave.get('remoteJid', '').split('@')[0], texto, d.get('pushName', ''), chave.get('id', '')))
    elif isinstance(payload, dict) and ('phone' in payload and ('text' in payload or 'type' in payload)):   # Z-API
        if not payload.get('fromMe') and not payload.get('isGroup'):
            texto = (payload.get('text') or {}).get('message', '') if isinstance(payload.get('text'), dict) else ''
            msgs.append((payload.get('phone', ''), texto, payload.get('senderName', ''), payload.get('messageId', '')))
    elif isinstance(payload, dict) and payload.get('telefone'):              # webhook genérico
        msgs.append((payload['telefone'], payload.get('mensagem', ''), payload.get('nome', ''), payload.get('id', '')))
    return [(normalizar_telefone(t), (x or '').strip(), n, i) for t, x, n, i in msgs if t and (x or '').strip()]


def localizar_paciente(clinica, telefone):
    """Compara DDD + últimos 8 dígitos (tolera o 9º dígito ausente em contas antigas do WhatsApp)."""
    d = ''.join(c for c in telefone if c.isdigit())
    if d.startswith('55'):
        d = d[2:]
    if len(d) < 10:
        return None
    ddd, final = d[:2], d[-8:]
    for p in Paciente.objects.filter(clinica=clinica, celular__isnull=False).exclude(celular='').filter(
            celular__endswith=final[-4:]):
        pd = ''.join(c for c in p.celular if c.isdigit())
        pd = pd[2:] if pd.startswith('55') and len(pd) > 11 else pd
        if pd[-8:] == final and pd[:2] == ddd:
            return p
    return None


def processar_mensagem(clinica, telefone, texto, nome='', id_externo=''):
    from agenda.models import Agendamento
    from agenda.services import mudar_status
    if id_externo and MensagemRecebida.objects.filter(clinica=clinica, id_externo=id_externo).exists():
        return None
    paciente = localizar_paciente(clinica, telefone)
    msg = MensagemRecebida.objects.create(clinica=clinica, telefone=telefone, nome_contato=nome[:150],
                                          paciente=paciente, texto=texto[:4000], id_externo=id_externo[:120])
    t = _norm(texto)
    if paciente and clinica.resposta_sim_nao and (t in SIM or t in NAO):
        clinica.ativar_fuso()
        proximo = Agendamento.objects.filter(
            paciente=paciente, inicio__gte=timezone.now(), inicio__lte=timezone.now() + timedelta(days=10),
            status__in=('agendado', 'confirmado')).order_by('inicio').first()
        if proximo:
            ini = timezone.localtime(proximo.inicio)
            if t in SIM and proximo.status == 'agendado':
                mudar_status(proximo, 'confirmado', origem='paciente')
                msg.acao, resposta = 'confirmou', (f'Presença confirmada para {ini:%d/%m} às {ini:%H:%M} com '
                                                   f'{proximo.medico}. Obrigado! ✅')
            elif t in SIM:
                msg.acao, resposta = 'ja_confirmado', f'Sua presença em {ini:%d/%m} às {ini:%H:%M} já está confirmada. 👍'
            else:
                mudar_status(proximo, 'cancelado', origem='paciente')
                msg.acao, resposta = 'cancelou', (f'Seu atendimento de {ini:%d/%m} às {ini:%H:%M} foi cancelado. '
                                                  'Se quiser remarcar, responda esta mensagem.')
                Lembrete.objects.create(clinica=clinica, origem='whatsapp',
                                        titulo=f'Paciente cancelou pelo WhatsApp: {paciente}',
                                        mensagem=f'{proximo}', link=reverse('agenda:detalhe', args=[proximo.pk]))
            msg.agendamento, msg.lida = proximo, True
            msg.save(update_fields=['acao', 'agendamento', 'lida'])
            enfileirar(clinica, paciente.nome, telefone=telefone, mensagem=resposta, evento='resposta_automatica',
                       agendamento=proximo, por_email=False, sms=False)
            return msg
    Lembrete.objects.filter(clinica=clinica, origem='conversa', concluido=False, mensagem=telefone).exists() or \
        Lembrete.objects.create(clinica=clinica, origem='conversa', titulo=f'Nova mensagem no WhatsApp: '
                                f'{paciente or nome or telefone}', mensagem=telefone,
                                link=reverse('notificacoes:conversa', args=[telefone]))
    return msg


@csrf_exempt
def webhook(request, codigo, token):
    clinica = Clinica.objects.filter(codigo_publico=codigo, ativa=True).first()
    if not clinica or not clinica.webhook_token or not secrets.compare_digest(token, clinica.webhook_token):
        return HttpResponseForbidden('token inválido')
    if request.method == 'GET':   # verificação da Meta
        if request.GET.get('hub.mode') == 'subscribe' and request.GET.get('hub.verify_token') == clinica.webhook_token:
            return HttpResponse(request.GET.get('hub.challenge', ''))
        return HttpResponse('ok')
    if len(request.body) > 512 * 1024:
        return HttpResponse(status=413)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'ok': False, 'erro': 'json inválido'}, status=400)
    n = 0
    for tel, texto, nome, idx in extrair(payload):
        if processar_mensagem(clinica, tel, texto, nome, idx):
            n += 1
    return JsonResponse({'ok': True, 'recebidas': n})


# ------------------------------------------------------------------ caixa de conversas
@acesso('callcenter')
def conversas(request):
    c = request.clinica
    q = request.GET.get('q', '').strip()
    base = MensagemRecebida.objects.filter(clinica=c)
    if q:
        base = base.filter(Q(telefone__icontains=q) | Q(paciente__nome__icontains=q) | Q(nome_contato__icontains=q) |
                           Q(texto__icontains=q))
    resumo = base.values('telefone').annotate(ultima=Max('criado_em'), nao_lidas=Count('id', filter=Q(lida=False))
                                               ).order_by('-ultima')[:100]
    lista = []
    for r in resumo:   # última mensagem de cada conversa
        m = MensagemRecebida.objects.filter(clinica=c, telefone=r['telefone']).select_related('paciente').first()
        lista.append({'telefone': r['telefone'], 'ultima': r['ultima'], 'nao_lidas': r['nao_lidas'], 'm': m})
    return render(request, 'notificacoes/conversas.html', {'lista': lista, 'q': q, 'webhook': url_webhook(c)
                                                           if tem_permissao(request, 'administrativo', 'editar') else ''})


@acesso('callcenter')
def conversa(request, telefone):
    c = request.clinica
    tel = normalizar_telefone(telefone)
    if request.method == 'POST' and tem_permissao(request, 'callcenter', 'editar'):
        texto = request.POST.get('texto', '').strip()
        if texto:
            p = localizar_paciente(c, tel)
            enfileirar(c, str(p or tel), telefone=tel, mensagem=texto, evento='conversa', por_email=False, sms=False)
            messages.success(request, 'Mensagem enviada.')
        return redirect('notificacoes:conversa', tel)
    recebidas = list(MensagemRecebida.objects.filter(clinica=c, telefone=tel).select_related('agendamento'))
    MensagemRecebida.objects.filter(clinica=c, telefone=tel, lida=False).update(lida=True)
    Lembrete.objects.filter(clinica=c, origem='conversa', mensagem=tel, concluido=False).update(concluido=True)
    enviadas = list(Notificacao.objects.filter(clinica=c, canal='whatsapp', destinatario=tel))
    fio = sorted([('in', m.criado_em, m) for m in recebidas] + [('out', n.criado_em, n) for n in enviadas],
                 key=lambda x: x[1])[-200:]
    paciente = localizar_paciente(c, tel)
    return render(request, 'notificacoes/conversa.html', {'tel': tel, 'fio': fio, 'paciente': paciente,
                                                          'pode_responder': tem_permissao(request, 'callcenter', 'editar')})
