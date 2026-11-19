from django.core.management.base import BaseCommand

from notificacoes.tarefas import processar_lembretes


class Command(BaseCommand):
    help = 'Envia lembretes aos pacientes (WhatsApp/e-mail), agenda diária aos médicos e alertas aos usuários.'

    def handle(self, *args, **opts):
        for clinica, r in processar_lembretes().items():
            self.stdout.write(f'{clinica}: {r}')
        self.stdout.write(self.style.SUCCESS('Lembretes processados.'))
