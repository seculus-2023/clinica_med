"""Confere se o sistema está configurado e conectado ao PostgreSQL (usado pelos .bat antes de iniciar)."""
import sys

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = 'Verifica a conexão com o banco PostgreSQL definido no .env.'

    def add_arguments(self, parser):
        parser.add_argument('--silencioso', action='store_true')

    def handle(self, *args, **o):
        db = settings.DATABASES['default']
        alvo = f"{db.get('USER')}@{db.get('HOST')}:{db.get('PORT')}/{db.get('NAME')}"
        if 'postgresql' not in db['ENGINE']:
            self.stderr.write(self.style.ERROR(
                f'O banco configurado não é PostgreSQL ({db["ENGINE"]}). Ajuste DB_ENGINE=postgresql no .env.'))
            sys.exit(2)
        try:
            with connection.cursor() as cur:
                cur.execute('SELECT version()')
                versao = cur.fetchone()[0].split(',')[0]
        except OperationalError as e:
            msg = str(e).strip().splitlines()[0] if str(e).strip() else repr(e)
            dica = ''
            baixo = msg.lower()
            if 'exist' in baixo and ('database' in baixo or 'banco' in baixo):
                dica = f'\n  -> O banco "{db.get("NAME")}" ainda não foi criado: rode configurar_postgres.bat'
            elif 'password' in baixo or 'senha' in baixo or 'autentica' in baixo:
                dica = '\n  -> Usuário ou senha incorretos: confira DB_USER e DB_PASSWORD no .env'
            elif 'connect' in msg.lower() or 'conectar' in msg.lower() or 'refused' in msg.lower():
                dica = '\n  -> O PostgreSQL não está respondendo: confira se o serviço está iniciado e DB_HOST/DB_PORT'
            self.stderr.write(self.style.ERROR(f'Sem conexão com o PostgreSQL ({alvo}): {msg}{dica}'))
            sys.exit(1)
        if not o['silencioso']:
            self.stdout.write(self.style.SUCCESS(f'PostgreSQL OK: {alvo} ({versao})'))
