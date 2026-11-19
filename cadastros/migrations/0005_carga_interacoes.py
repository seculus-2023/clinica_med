from django.db import migrations


def carregar(apps, schema_editor):
    from cadastros.interacoes_base import FONTE, INTERACOES
    Interacao = apps.get_model('cadastros', 'InteracaoMedicamentosa')
    for a, b, grav, efeito, conduta in INTERACOES:
        Interacao.objects.get_or_create(substancia_a=a, substancia_b=b,
                                        defaults={'gravidade': grav, 'efeito': efeito, 'conduta': conduta,
                                                  'fonte': FONTE})


class Migration(migrations.Migration):
    dependencies = [('cadastros', '0004_alter_interacaomedicamentosa_substancia_a_and_more')]
    operations = [migrations.RunPython(carregar, migrations.RunPython.noop)]
