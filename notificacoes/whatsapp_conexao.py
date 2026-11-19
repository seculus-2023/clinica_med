"""Conexão do número de WhatsApp da clínica com o provedor (status e QR Code da Evolution API)."""
import requests
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render

from contas.permissoes import acesso

from .services import numero_remetente


def _instancia(c):
    return c.whatsapp_instancia or numero_remetente(c) or 'medaccess'


def status(c):
    """Retorna {'ok': bool, 'estado': str, 'detalhe': str}."""
    prov, url, token = c.whatsapp_provedor, (c.whatsapp_api_url or '').rstrip('/'), c.whatsapp_token
    try:
        if prov == 'simulado':
            return {'ok': False, 'estado': 'simulado', 'detalhe': 'Modo simulado: nada é enviado automaticamente.'}
        if prov == 'evolution':
            r = requests.get(f'{url}/instance/connectionState/{_instancia(c)}', headers={'apikey': token}, timeout=15)
            if r.status_code == 404:
                return {'ok': False, 'estado': 'sem_instancia', 'detalhe': 'Instância ainda não criada.'}
            estado = (r.json().get('instance') or {}).get('state', 'desconhecido')
            return {'ok': estado == 'open', 'estado': estado,
                    'detalhe': 'Conectado.' if estado == 'open' else 'Leia o QR Code com o WhatsApp da clínica.'}
        if prov == 'zapi':
            r = requests.get(f'{url}/status', headers={'Client-Token': token}, timeout=15)
            d = r.json() if r.ok else {}
            return {'ok': bool(d.get('connected')), 'estado': 'conectado' if d.get('connected') else 'desconectado',
                    'detalhe': d.get('error') or ('Conectado.' if d.get('connected') else
                                                  'Conecte o número pelo painel da Z-API.')}
        if prov == 'meta':
            base = url or 'https://graph.facebook.com/v20.0'
            r = requests.get(f'{base}/{c.whatsapp_instancia}', params={'fields': 'display_phone_number,verified_name'},
                             headers={'Authorization': f'Bearer {token}'}, timeout=15)
            d = r.json()
            if r.ok:
                return {'ok': True, 'estado': 'conectado',
                        'detalhe': f"{d.get('verified_name', '')} {d.get('display_phone_number', '')}".strip()}
            return {'ok': False, 'estado': 'erro', 'detalhe': (d.get('error') or {}).get('message', r.text[:200])}
        if prov == 'webhook':
            return {'ok': bool(url), 'estado': 'webhook', 'detalhe': url or 'Informe a URL do webhook.'}
    except requests.RequestException as e:
        return {'ok': False, 'estado': 'erro', 'detalhe': f'Sem comunicação com o provedor: {e}'}
    except ValueError:
        return {'ok': False, 'estado': 'erro', 'detalhe': 'Resposta inválida do provedor.'}
    return {'ok': False, 'estado': 'desconhecido', 'detalhe': ''}


def qrcode_evolution(c):
    url, token, inst = (c.whatsapp_api_url or '').rstrip('/'), c.whatsapp_token, _instancia(c)
    h = {'apikey': token}
    r = requests.get(f'{url}/instance/connect/{inst}', headers=h, timeout=20)
    if r.status_code == 404:  # cria a instância e tenta de novo
        requests.post(f'{url}/instance/create', headers=h, timeout=20,
                      json={'instanceName': inst, 'qrcode': True, 'integration': 'WHATSAPP-BAILEYS',
                            'number': numero_remetente(c)})
        r = requests.get(f'{url}/instance/connect/{inst}', headers=h, timeout=20)
    d = r.json() if r.ok else {}
    img = d.get('base64') or (d.get('qrcode') or {}).get('base64') or ''
    return img, d.get('pairingCode') or ''


@acesso('administrativo', 'editar')
def conexao(request):
    c = request.clinica
    if not c.whatsapp:
        messages.warning(request, 'Cadastre primeiro o número de WhatsApp da clínica.')
    st = status(c)
    qr, codigo = '', ''
    if c.whatsapp_provedor == 'evolution' and not st['ok'] and c.whatsapp_api_url and c.whatsapp_token:
        try:
            qr, codigo = qrcode_evolution(c)
        except requests.RequestException as e:
            st['detalhe'] = f'Erro ao obter QR Code: {e}'
    if request.GET.get('json'):
        return JsonResponse({'status': st, 'qr': qr})
    return render(request, 'notificacoes/conexao.html', {'st': st, 'qr': qr, 'codigo': codigo, 'c': c,
                                                         'instancia': _instancia(c)})


@acesso('administrativo', 'editar')
def desconectar(request):
    c = request.clinica
    if request.method == 'POST' and c.whatsapp_provedor == 'evolution':
        try:
            requests.delete(f'{c.whatsapp_api_url.rstrip("/")}/instance/logout/{_instancia(c)}',
                            headers={'apikey': c.whatsapp_token}, timeout=15)
            messages.info(request, 'WhatsApp desconectado.')
        except requests.RequestException as e:
            messages.error(request, str(e))
    return redirect('notificacoes:conexao')
