from django.apps import AppConfig


class SenhasConfig(AppConfig):
    name = 'senhas'
    verbose_name = 'Senhas de atendimento'

    def ready(self):
        from . import signals  # noqa: F401
