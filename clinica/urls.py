from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from painel import pwa

urlpatterns = [
    path('manifest.webmanifest', pwa.manifest, name='pwa_manifest'),
    path('sw.js', pwa.service_worker, name='pwa_sw'),
    path('offline/', pwa.offline, name='pwa_offline'),
    path('admin/', admin.site.urls),
    path('', include('painel.urls')),
    path('conta/', include('contas.urls')),
    path('cadastros/', include('cadastros.urls')),
    path('agenda/', include('agenda.urls')),
    path('estoque/', include('estoque.urls')),
    path('financeiro/', include('financeiro.urls')),
    path('prontuario/', include('prontuario.urls')),
    path('convenios/', include('convenios.urls')),
    path('portal/', include('portal.urls')),
    path('assinatura/', include('assinaturas.urls')),
    path('documentos/', include('documentos.urls')),
    path('callcenter/', include('callcenter.urls')),
    path('notificacoes/', include('notificacoes.urls')),
    path('medico/', include('areamedica.urls')),
    path('senhas/', include('senhas.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

handler403 = 'painel.views.erro_403'
