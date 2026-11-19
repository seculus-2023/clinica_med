from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Clinica, Lembrete, Perfil, Usuario, Vinculo


class VinculoInline(admin.TabularInline):
    model = Vinculo
    extra = 0


@admin.register(Usuario)
class UsuarioAdmin(UserAdmin):
    inlines = [VinculoInline]
    fieldsets = UserAdmin.fieldsets + (('Contato', {'fields': ('telefone',)}),)


admin.site.register(Clinica)
admin.site.register(Perfil)
admin.site.register(Lembrete)
admin.site.site_header = 'MedAccess - Administração'
