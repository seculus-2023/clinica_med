"""Cria o banco PostgreSQL definido no .env, aplica as migrações e (opcionalmente) copia os dados do SQLite.

Uso:
    python configurar_postgres.py               -> cria o banco (se não existir) e aplica as migrações
    python configurar_postgres.py --copiar      -> também copia os dados do db.sqlite3 para o PostgreSQL
    python configurar_postgres.py --demo        -> também carrega os dados de demonstração (banco vazio)
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.chdir(BASE)
sys.path.insert(0, str(BASE))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'clinica.settings')
os.environ.setdefault('NOTIFICACOES_ASSINCRONAS', '0')
os.environ.setdefault('AUTO_LEMBRETES', '0')


def criar_banco(cfg):
    try:
        import psycopg as driver
        from psycopg import sql
    except ImportError:
        import psycopg2 as driver
        from psycopg2 import sql
    con = driver.connect(dbname='postgres', user=cfg['USER'], password=cfg['PASSWORD'], host=cfg['HOST'],
                         port=cfg['PORT'])
    con.autocommit = True
    with con.cursor() as cur:
        cur.execute('SELECT 1 FROM pg_database WHERE datname = %s', [cfg['NAME']])
        if cur.fetchone():
            print(f'Banco "{cfg["NAME"]}" já existe.')
        else:
            cur.execute(sql.SQL("CREATE DATABASE {} ENCODING 'UTF8' TEMPLATE template0").format(
                sql.Identifier(cfg['NAME'])))
            print(f'Banco "{cfg["NAME"]}" criado.')
    con.close()


def main():
    copiar, demo = '--copiar' in sys.argv, '--demo' in sys.argv
    from clinica import settings as conf  # lê o .env
    cfg = conf.DATABASES['default']
    if 'postgresql' not in cfg['ENGINE']:
        sys.exit('O .env não está com DB_ENGINE=postgresql.')
    print(f'PostgreSQL: {cfg["USER"]}@{cfg["HOST"]}:{cfg["PORT"]}/{cfg["NAME"]}')

    dump = None
    if copiar:
        sqlite = BASE / 'db.sqlite3'
        if not sqlite.exists():
            sys.exit('db.sqlite3 não encontrado para copiar.')
        dump = Path(tempfile.gettempdir()) / 'medaccess_sqlite.json'
        print('Exportando dados do SQLite...')
        amb = dict(os.environ, DB_ENGINE='sqlite', DB_NAME='db.sqlite3')
        subprocess.run([sys.executable, 'manage.py', 'dumpdata', '--natural-foreign', '--natural-primary',
                        '-e', 'contenttypes', '-e', 'auth.permission', '-e', 'sessions', '-e', 'admin.logentry',
                        '--indent', '0', '-o', str(dump)], check=True, env=amb)

    criar_banco(cfg)
    import django
    django.setup()
    from django.core.management import call_command
    call_command('migrate', interactive=False)
    if dump:
        from cadastros.models import InteracaoMedicamentosa
        # a migração já carregou a base de interações; remove para não duplicar com o SQLite
        InteracaoMedicamentosa.objects.all().delete()
        print('Importando dados no PostgreSQL...')
        call_command('loaddata', str(dump))
        _resetar_sequencias()
        dump.unlink(missing_ok=True)
        print('Dados copiados do SQLite.')
    elif demo:
        call_command('popular_demo')
    print('Pronto! Inicie o sistema com iniciar.bat.')


def _resetar_sequencias():
    """Ajusta os contadores de ID após importar dados com IDs fixos."""
    from io import StringIO

    from django.apps import apps
    from django.core.management import call_command
    from django.db import connection
    saida = StringIO()
    rotulos = [a.label for a in apps.get_app_configs() if a.models_module]
    call_command('sqlsequencereset', *rotulos, stdout=saida, no_color=True)
    with connection.cursor() as cur:
        cur.execute(saida.getvalue())


if __name__ == '__main__':
    main()
