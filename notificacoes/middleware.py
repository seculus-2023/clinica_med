import threading
import time

from django.conf import settings

_trava = threading.Lock()
_ultima = {'t': 0.0}


class AutoLembretesMiddleware:
    """Processa lembretes periodicamente enquanto o sistema está em uso.

    Dispensa configurar um agendador do Windows/cron. Para produção recomenda-se também
    agendar: python manage.py processar_lembretes (a cada 10 minutos).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if settings.AUTO_LEMBRETES and time.time() - _ultima['t'] > settings.AUTO_LEMBRETES_INTERVALO_MIN * 60:
            if _trava.acquire(blocking=False):
                _ultima['t'] = time.time()
                threading.Thread(target=self._rodar, daemon=True).start()
        return response

    @staticmethod
    def _rodar():
        try:
            from .tarefas import processar_lembretes
            processar_lembretes()
        except Exception:  # noqa: BLE001
            import logging
            logging.getLogger('notificacoes').exception('Falha no processamento automático de lembretes')
        finally:
            from django.db import connection
            connection.close()
            _trava.release()
