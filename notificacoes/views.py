from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from contas.permissoes import acesso

from .models import Notificacao
from .services import enfileirar, processar
from .tarefas import processar_lembretes


@acesso('administrativo')
def lista(request):
    qs = Notificacao.objects.filter(clinica=request.clinica).select_related('agendamento')
    for campo in ('canal', 'status'):
        if request.GET.get(campo):
            qs = qs.filter(**{campo: request.GET[campo]})
    return render(request, 'notificacoes/lista.html', {
        'notificacoes': qs[:300], 'canais': Notificacao.CANAIS, 'status': Notificacao.STATUS,
        'canal_sel': request.GET.get('canal', ''), 'status_sel': request.GET.get('status', '')})


@acesso('administrativo', 'editar')
@require_POST
def reenviar(request, pk):
    n = get_object_or_404(Notificacao, pk=pk, clinica=request.clinica)
    n.status, n.erro = 'pendente', ''
    n.save()
    processar([n.pk])
    n.refresh_from_db()
    messages.info(request, f'Reenvio: {n.get_status_display()}' + (f' - {n.erro}' if n.erro else ''))
    return redirect('notificacoes:lista')


@acesso('administrativo', 'editar')
@require_POST
def processar_agora(request):
    r = processar_lembretes()
    messages.success(request, f'Lembretes processados: {r.get(request.clinica.nome, {})}')
    return redirect('notificacoes:lista')


@acesso('administrativo', 'editar')
@require_POST
def testar(request):
    c = request.clinica
    ids = enfileirar(c, str(request.user), telefone=request.POST.get('telefone'), email=request.POST.get('email'),
                     sms=bool(request.POST.get('sms')),
                     assunto='Teste de notificação', mensagem=f'Teste de envio do sistema - {c.nome}.',
                     evento='teste')
    messages.info(request, f'{len(ids)} mensagem(ns) de teste enfileirada(s). Confira o status abaixo.')
    return redirect('notificacoes:lista')
