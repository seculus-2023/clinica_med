from django.apps import AppConfig


class AgendaConfig(AppConfig):
    name = 'agenda'
    verbose_name = 'Agenda'

    def ready(self):
        from . import services  # noqa: F401  (registra os sinais)
