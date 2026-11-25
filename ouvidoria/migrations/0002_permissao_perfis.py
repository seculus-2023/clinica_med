from django.db import migrations


def liberar_administradores(apps, schema_editor):
    """Módulo novo: perfis que administram a clínica passam a editar a ouvidoria; os demais ficam sem acesso."""
    Perfil = apps.get_model('contas', 'Perfil')
    for perfil in Perfil.objects.all():
        if perfil.permissoes.get('administrativo') == 'editar' and 'ouvidoria' not in perfil.permissoes:
            perfil.permissoes['ouvidoria'] = 'editar'
            perfil.save(update_fields=['permissoes'])


class Migration(migrations.Migration):
    dependencies = [('ouvidoria', '0001_initial'), ('contas', '0001_initial')]
    operations = [migrations.RunPython(liberar_administradores, migrations.RunPython.noop)]
