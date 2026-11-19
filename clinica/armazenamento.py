"""Armazenamento privado: arquivos fora de /media, servidos só por views com verificação de permissão."""
from functools import lru_cache

from django.conf import settings
from django.core.files.storage import FileSystemStorage


@lru_cache(maxsize=1)
def privado():
    """Callable usado em FileField(storage=privado): o caminho é resolvido em execução (portável entre servidores)."""
    return FileSystemStorage(location=settings.BASE_DIR / 'privado')
