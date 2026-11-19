from django.db import migrations

PADRAO = {'Administrador': 'editar', 'Financeiro': 'editar', 'Recepção': 'ver'}


def adicionar(apps, schema_editor):
    Perfil = apps.get_model('contas', 'Perfil')
    for p in Perfil.objects.all():
        if 'convenios' in (p.permissoes or {}):
            continue
        nivel = PADRAO.get(p.nome) or ('editar' if p.permissoes.get('financeiro') == 'editar' else 'nenhum')
        p.permissoes = dict(p.permissoes or {}, convenios=nivel)
        p.save(update_fields=['permissoes'])


class Migration(migrations.Migration):
    dependencies = [('convenios', '0001_initial'), ('contas', '0004_clinica_cnes')]
    operations = [migrations.RunPython(adicionar, migrations.RunPython.noop)]
