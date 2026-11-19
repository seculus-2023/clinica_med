from django.db import migrations


def carregar(apps, schema_editor):
    from cadastros.interacoes_base import FONTE, INTERACOES_EXTRA
    Interacao = apps.get_model('cadastros', 'InteracaoMedicamentosa')
    for a, b, grav, efeito, conduta in INTERACOES_EXTRA:
        Interacao.objects.get_or_create(substancia_a=a, substancia_b=b,
                                        defaults={'gravidade': grav, 'efeito': efeito, 'conduta': conduta,
                                                  'fonte': FONTE})


class Migration(migrations.Migration):
    dependencies = [('cadastros', '0009_tipoatendimento_recurso')]
    operations = [migrations.RunPython(carregar, migrations.RunPython.noop)]
