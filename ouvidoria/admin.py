from django.contrib import admin

from .models import Andamento, Manifestacao, Setor


class AndamentoInline(admin.TabularInline):
    model = Andamento
    extra = 0
    readonly_fields = ['tipo', 'texto', 'publico', 'usuario', 'destino', 'setor', 'criado_em']


@admin.register(Manifestacao)
class ManifestacaoAdmin(admin.ModelAdmin):
    list_display = ['protocolo', 'clinica', 'tipo', 'status', 'prazo', 'criado_em']
    list_filter = ['clinica', 'tipo', 'status', 'canal']
    search_fields = ['protocolo', 'assunto']
    inlines = [AndamentoInline]


admin.site.register(Setor)
