import secrets

from django.db import migrations


def preencher(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    for d in Documento.objects.filter(codigo_verificacao=''):
        h = secrets.token_hex(8).upper()
        d.codigo_verificacao = '-'.join(h[i:i + 4] for i in range(0, 16, 4))
        d.save(update_fields=['codigo_verificacao'])


class Migration(migrations.Migration):
    dependencies = [('documentos', '0002_documento_codigo_verificacao_documentoassinado')]
    operations = [migrations.RunPython(preencher, migrations.RunPython.noop)]
