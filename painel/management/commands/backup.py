"""Backup do banco de dados e dos arquivos (anexos do prontuário, logos).

Uso:  python manage.py backup [--destino D:\\Backups] [--manter 30]
Agende diariamente (Agendador de Tarefas do Windows / cron) para backups automáticos.
"""
import shutil
import sqlite3
import zipfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = 'Gera um .zip com o banco de dados e os arquivos do sistema, mantendo os N mais recentes.'

    def add_arguments(self, parser):
        parser.add_argument('--destino', default=str(settings.BASE_DIR / 'backups'))
        parser.add_argument('--manter', type=int, default=30)

    @staticmethod
    def _pg_dump(db, saida):
        """Gera o dump (formato custom, restaurável com pg_restore)."""
        import glob
        import os
        import subprocess
        exe = os.environ.get('PG_DUMP') or shutil.which('pg_dump')
        if not exe:
            candidatos = sorted(glob.glob(r'C:\Program Files\PostgreSQL\*\bin\pg_dump.exe'))
            exe = candidatos[-1] if candidatos else None
        if not exe:
            raise RuntimeError('pg_dump não encontrado. Informe o caminho em PG_DUMP no .env.')
        amb = dict(os.environ, PGPASSWORD=str(db.get('PASSWORD') or ''))
        subprocess.run([exe, '-h', str(db.get('HOST') or 'localhost'), '-p', str(db.get('PORT') or '5432'),
                        '-U', str(db.get('USER') or 'postgres'), '-F', 'c', '-f', str(saida), str(db['NAME'])],
                       check=True, env=amb, capture_output=True)

    def handle(self, *args, **o):
        destino = Path(o['destino'])
        destino.mkdir(parents=True, exist_ok=True)
        carimbo = timezone.localtime().strftime('%Y%m%d_%H%M%S')
        arquivo = destino / f'medaccess_{carimbo}.zip'
        db = settings.DATABASES['default']
        tmp_db = destino / f'_db_{carimbo}.sqlite3'
        with zipfile.ZipFile(arquivo, 'w', zipfile.ZIP_DEFLATED) as z:
            if db['ENGINE'].endswith('sqlite3'):
                origem = sqlite3.connect(str(db['NAME']))
                copia = sqlite3.connect(str(tmp_db))
                origem.backup(copia)  # cópia consistente mesmo com o sistema em uso
                copia.close()
                origem.close()
                z.write(tmp_db, 'db.sqlite3')
            elif 'postgresql' in db['ENGINE']:
                tmp_pg = destino / f'_db_{carimbo}.dump'
                self._pg_dump(db, tmp_pg)
                z.write(tmp_pg, 'db_postgresql.dump')
                tmp_pg.unlink(missing_ok=True)
            else:
                self.stdout.write(self.style.WARNING('Banco MySQL: use mysqldump; copiando só arquivos.'))
            for pasta in (settings.MEDIA_ROOT, settings.BASE_DIR / 'privado'):
                pasta = Path(pasta)
                if pasta.exists():
                    for f in pasta.rglob('*'):
                        if f.is_file():
                            z.write(f, f'{pasta.name}/{f.relative_to(pasta)}')
        tmp_db.unlink(missing_ok=True)
        antigos = sorted(destino.glob('medaccess_*.zip'))[:-o['manter']]
        for a in antigos:
            a.unlink()
        self.stdout.write(self.style.SUCCESS(f'Backup criado: {arquivo} ({arquivo.stat().st_size // 1024} KB). '
                                             f'{len(antigos)} antigo(s) removido(s).'))
        if shutil.disk_usage(destino).free < 1024 ** 3:
            self.stdout.write(self.style.WARNING('Menos de 1 GB livre no destino do backup.'))
