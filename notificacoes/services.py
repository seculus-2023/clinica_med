"""Envio de notificações por WhatsApp e e-mail.

Provedores WhatsApp suportados (configurados por clínica):
  - simulado : apenas registra a mensagem (gera link wa.me para envio manual)
  - meta     : WhatsApp Cloud API  -> POST {url|https://graph.facebook.com/v20.0}/{phone_id}/messages
  - evolution: Evolution API       -> POST {url}/message/sendText/{instancia}  (header apikey)
  - zapi     : Z-API               -> POST {url}/send-text  (url já com instância/token; header Client-Token)
  - webhook  : POST JSON {telefone, mensagem, clinica} na URL informada
Obs.: a Cloud API da Meta exige templates aprovados para iniciar conversas fora da janela de 24h.
"""
import logging
import threading

from django.conf import settings
from django.core.mail import EmailMessage
from django.db import transaction
from django.utils import timezone

from .models import Notificacao

log = logging.getLogger('notificacoes')

EVENTOS = {
    'agendamento': ('msg_agendamento', 'Agendamento confirmado'),
    'reagendamento': ('msg_agendamento', 'Seu atendimento foi reagendado'),
    'lembrete': ('msg_lembrete', 'Lembrete do seu atendimento'),
    'cancelamento': ('msg_cancelamento', 'Atendimento cancelado'),
    'nps': ('msg_nps', 'Como foi seu atendimento?'),
}


def normalizar_telefone(numero):
    d = ''.join(c for c in str(numero or '') if c.isdigit())
    if not d:
        return ''
    if len(d) <= 11:
        d = '55' + d
    return d


class _Seguro(dict):
    def __missing__(self, chave):
        return '{' + chave + '}'


def montar_texto(modelo, clinica, paciente, medico=None, ag=None):
    clinica.ativar_fuso()
    dados = {'paciente': paciente.nome.split()[0] if paciente and paciente.nome else '', 'paciente_completo': paciente.nome if paciente
             else '', 'clinica': clinica.nome, 'medico': medico.nome if medico else '',
             'telefone_clinica': clinica.telefone or clinica.whatsapp, 'whatsapp_clinica': clinica.whatsapp,
             'link_portal': settings.SITE_URL + f'/portal/{clinica.codigo_publico}/',
             'endereco': clinica.endereco}
    if ag:
        ini = timezone.localtime(ag.inicio)
        dados.update({'data': ini.strftime('%d/%m/%Y'), 'hora': ini.strftime('%H:%M'), 'tipo': ag.tipo.nome,
                      'link_confirmacao': ag.link_confirmacao, 'link_checkin': ag.link_checkin,
                      'link_avaliacao': ag.link_avaliacao, 'link_teleconsulta': ag.link_teleconsulta})
    texto = modelo.format_map(_Seguro(dados))
    if ag and ag.teleconsulta and '{link_teleconsulta}' not in modelo and ag.status not in ('cancelado', 'concluido'):
        texto += f'\nTeleconsulta - entre na sala de vídeo no horário: {ag.link_teleconsulta}'
    return texto


def montar_mensagem(ag, modelo):
    return montar_texto(modelo, ag.clinica, ag.paciente, ag.medico, ag)


# ---------------- envio de baixo nível ----------------
def numero_remetente(clinica):
    """Número de WhatsApp da clínica (cadastro da clínica logada) usado como remetente."""
    return normalizar_telefone(clinica.whatsapp)


def _enviar_whatsapp(clinica, telefone, mensagem):
    import requests
    prov = clinica.whatsapp_provedor
    remetente = numero_remetente(clinica)
    if prov == 'simulado':
        return 'simulado'
    if not remetente:
        raise RuntimeError('Cadastre o número de WhatsApp da clínica em Administrativo > Configurações.')
    token, url = clinica.whatsapp_token, (clinica.whatsapp_api_url or '').rstrip('/')
    # Na Evolution/Z-API a instância conectada é a do número da clínica; se não informada, usa o próprio número.
    inst = clinica.whatsapp_instancia or remetente
    if prov == 'meta':
        base = url or 'https://graph.facebook.com/v20.0'
        r = requests.post(f'{base}/{inst}/messages', timeout=20, headers={'Authorization': f'Bearer {token}'},
                          json={'messaging_product': 'whatsapp', 'to': telefone, 'type': 'text',
                                'text': {'body': mensagem}})
    elif prov == 'evolution':
        r = requests.post(f'{url}/message/sendText/{inst}', timeout=20, headers={'apikey': token},
                          json={'number': telefone, 'text': mensagem})
    elif prov == 'zapi':
        r = requests.post(f'{url}/send-text', timeout=20, headers={'Client-Token': token},
                          json={'phone': telefone, 'message': mensagem})
    else:
        r = requests.post(url, timeout=20, headers={'Authorization': f'Bearer {token}'} if token else {},
                          json={'remetente': remetente, 'telefone': telefone, 'mensagem': mensagem,
                                'clinica': clinica.nome, 'instancia': inst})
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:300]}')
    return 'enviado'


def conexao_email(clinica):
    """SMTP próprio da clínica (se configurado) ou o do .env."""
    from django.core.mail import get_connection
    if clinica.smtp_host:
        return get_connection('django.core.mail.backends.smtp.EmailBackend', host=clinica.smtp_host,
                              port=clinica.smtp_porta, username=clinica.smtp_usuario, password=clinica.smtp_senha,
                              use_tls=clinica.smtp_tls and clinica.smtp_porta != 465,
                              use_ssl=clinica.smtp_porta == 465, timeout=20)
    return get_connection()


def _enviar_email(clinica, para, assunto, mensagem):
    endereco = clinica.email_remetente or (clinica.smtp_usuario if '@' in clinica.smtp_usuario else '')
    remetente = f'{clinica.nome} <{endereco}>' if endereco else settings.DEFAULT_FROM_EMAIL
    EmailMessage(subject=f'{assunto} - {clinica.nome}', body=mensagem, from_email=remetente, to=[para],
                 reply_to=[clinica.email] if clinica.email else None, connection=conexao_email(clinica)).send()
    return 'enviado'


def _enviar_sms(clinica, telefone, mensagem):
    import requests
    prov = clinica.sms_provedor
    texto = mensagem[:600]
    if prov == 'twilio':
        r = requests.post(f'https://api.twilio.com/2010-04-01/Accounts/{clinica.sms_conta}/Messages.json',
                          auth=(clinica.sms_conta, clinica.sms_token), timeout=20,
                          data={'From': clinica.sms_remetente, 'To': '+' + telefone, 'Body': texto})
    elif prov == 'zenvia':
        r = requests.post('https://api.zenvia.com/v2/channels/sms/messages', timeout=20,
                          headers={'X-API-TOKEN': clinica.sms_token},
                          json={'from': clinica.sms_remetente, 'to': telefone,
                                'contents': [{'type': 'text', 'text': texto}]})
    elif prov == 'webhook':
        r = requests.post(clinica.sms_url, timeout=20,
                          headers={'Authorization': f'Bearer {clinica.sms_token}'} if clinica.sms_token else {},
                          json={'telefone': telefone, 'mensagem': texto, 'remetente': clinica.sms_remetente,
                                'clinica': clinica.nome})
    else:
        raise RuntimeError('Provedor de SMS não configurado.')
    if r.status_code >= 400:
        raise RuntimeError(f'HTTP {r.status_code}: {r.text[:300]}')
    return 'enviado'


def processar(notificacao_ids):
    for n in Notificacao.objects.filter(pk__in=notificacao_ids).select_related('clinica'):
        try:
            if n.canal == 'whatsapp':
                n.status = _enviar_whatsapp(n.clinica, n.destinatario, n.mensagem)
            elif n.canal == 'sms':
                n.status = _enviar_sms(n.clinica, n.destinatario, n.mensagem)
            else:
                n.status = _enviar_email(n.clinica, n.destinatario, n.assunto, n.mensagem)
            n.enviado_em = timezone.now()
        except Exception as e:  # noqa: BLE001 - registra qualquer falha do provedor
            log.warning('Falha ao enviar notificação %s: %s', n.pk, e)
            n.status, n.erro = 'erro', str(e)[:1000]
        n.save(update_fields=['status', 'enviado_em', 'erro', 'atualizado_em'])


def _processar_thread(ids):
    from django.db import connection
    try:
        processar(ids)
    finally:
        connection.close()


def _despachar(ids):
    if not ids:
        return
    if settings.NOTIFICACOES_ASSINCRONAS:
        transaction.on_commit(lambda: threading.Thread(target=_processar_thread, args=(ids,), daemon=True).start())
    else:
        transaction.on_commit(lambda: processar(ids))


def enfileirar(clinica, nome, telefone=None, email=None, assunto='', mensagem='', evento='', agendamento=None,
               whatsapp=True, por_email=True, sms=True, mensagem_whatsapp=None):
    ids = []
    tel = normalizar_telefone(telefone)
    if sms and clinica.notificar_sms and clinica.sms_provedor != 'nenhum' and tel:
        ids.append(Notificacao.objects.create(clinica=clinica, canal='sms', destinatario=tel,
                                              remetente=clinica.sms_remetente, nome_destinatario=nome,
                                              mensagem=mensagem, evento=evento, agendamento=agendamento).pk)
    if whatsapp and clinica.notificar_whatsapp and tel:
        ids.append(Notificacao.objects.create(clinica=clinica, canal='whatsapp', destinatario=tel,
                                              remetente=numero_remetente(clinica),
                                              nome_destinatario=nome, mensagem=mensagem_whatsapp or mensagem,
                                              evento=evento, agendamento=agendamento).pk)
    if por_email and clinica.notificar_email and email:
        ids.append(Notificacao.objects.create(clinica=clinica, canal='email', destinatario=email,
                                              remetente=clinica.email_remetente or settings.DEFAULT_FROM_EMAIL,
                                              nome_destinatario=nome, assunto=assunto, mensagem=mensagem,
                                              evento=evento, agendamento=agendamento).pk)
    _despachar(ids)
    return ids


def notificar_agendamento(ag, evento, forcar=False):
    campo, assunto = EVENTOS.get(evento, EVENTOS['lembrete'])
    p = ag.paciente
    msg = montar_mensagem(ag, getattr(ag.clinica, campo))
    msg_wpp = msg
    if (evento in ('agendamento', 'reagendamento', 'lembrete') and ag.clinica.resposta_sim_nao
            and ag.clinica.whatsapp_provedor != 'simulado'):
        msg_wpp = msg + '\n\nResponda *SIM* para confirmar ou *NÃO* para cancelar.'
    return enfileirar(ag.clinica, p.nome, telefone=p.celular, email=p.email, assunto=assunto, mensagem=msg,
                      mensagem_whatsapp=msg_wpp,
                      evento=evento, agendamento=ag, whatsapp=p.aceita_whatsapp or forcar,
                      por_email=p.aceita_email or forcar,
                      sms=(p.aceita_sms or forcar) and evento in ('agendamento', 'reagendamento', 'lembrete',
                                                                  'cancelamento'))
