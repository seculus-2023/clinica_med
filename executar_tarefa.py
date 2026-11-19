"""Executa um comando do Django sem janela (pythonw / Agendador de Tarefas), gravando a saída em logs/tarefas.log.

Uso: pythonw executar_tarefa.py processar_lembretes
     pythonw executar_tarefa.py backup --manter 30
"""
import os
import sys
import traceback
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
os.makedirs(os.path.join(BASE, 'logs'), exist_ok=True)
caminho_log = os.path.join(BASE, 'logs', 'tarefas.log')
if os.path.exists(caminho_log) and os.path.getsize(caminho_log) > 5 * 1024 * 1024:
    os.replace(caminho_log, caminho_log + '.1')
log = open(caminho_log, 'a', encoding='utf-8', buffering=1)
sys.stdout = sys.stderr = log
os.chdir(BASE)
sys.path.insert(0, BASE)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'clinica.settings')
os.environ.setdefault('NOTIFICACOES_ASSINCRONAS', '0')  # envia na hora (o processo termina em seguida)

codigo = 0
print(f'[{datetime.now():%d/%m/%Y %H:%M:%S}] {" ".join(sys.argv[1:])}')
try:
    import django
    django.setup()
    from django.core.management import call_command
    call_command(*sys.argv[1:], stdout=log, stderr=log)
except Exception:  # noqa: BLE001
    traceback.print_exc()
    codigo = 1
finally:
    log.flush()
sys.exit(codigo)
