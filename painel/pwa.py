from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.templatetags.static import static


def manifest(request):
    return JsonResponse({
        'name': 'MedAccess - Gestão de Clínicas',
        'short_name': 'MedAccess',
        'description': 'Agenda, prontuário, financeiro, estoque e relacionamento com pacientes.',
        'id': '/',
        'start_url': '/?origem=pwa',
        'scope': '/',
        'display': 'standalone',
        'orientation': 'any',
        'background_color': '#0b1f24',
        'theme_color': '#139e86',
        'lang': 'pt-BR',
        'icons': [
            {'src': static('icons/icon-192.png'), 'sizes': '192x192', 'type': 'image/png'},
            {'src': static('icons/icon-512.png'), 'sizes': '512x512', 'type': 'image/png'},
            {'src': static('icons/icon-maskable-512.png'), 'sizes': '512x512', 'type': 'image/png',
             'purpose': 'maskable'},
        ],
        'shortcuts': [
            {'name': 'Agenda do dia', 'url': '/agenda/dia/', 'icons': [{'src': static('icons/icon-192.png'),
                                                                        'sizes': '192x192'}]},
            {'name': 'Novo agendamento', 'url': '/agenda/novo/', 'icons': [{'src': static('icons/icon-192.png'),
                                                                            'sizes': '192x192'}]},
        ],
    }, content_type='application/manifest+json')


def service_worker(request):
    js = render_to_string('pwa/sw.js', {'versao': settings.PWA_VERSAO})
    resp = HttpResponse(js, content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    resp['Cache-Control'] = 'no-cache'
    return resp


def offline(request):
    return render(request, 'pwa/offline.html')
