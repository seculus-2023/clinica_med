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


@acesso(None)
def novidades(request):
    """Lembretes e mensagens novos desde o último aviso (para as notificações do app)."""
    from datetime import datetime
    from django.db.models import Q
    from django.http import JsonResponse
    from django.utils import timezone

    from contas.models import Lembrete

    from .models import MensagemRecebida
    try:
        desde = datetime.fromtimestamp(float(request.GET.get('desde') or 0), tz=timezone.get_current_timezone())
    except (ValueError, OSError):
        desde = timezone.now()
    agora = timezone.now()
    itens = []
    for lem in Lembrete.objects.filter(clinica=request.clinica, concluido=False, data_hora__lte=agora).filter(
            Q(usuario=request.user) | Q(usuario__isnull=True)).filter(Q(criado_em__gt=desde) | Q(data_hora__gt=desde)).order_by('-criado_em')[:10]:
        itens.append({'id': f'l{lem.pk}', 'titulo': lem.titulo, 'texto': lem.mensagem[:180], 'url': lem.link or '/conta/lembretes/'})
    from contas.permissoes import tem_permissao
    if tem_permissao(request, 'callcenter'):
        n = MensagemRecebida.objects.filter(clinica=request.clinica, lida=False, criado_em__gt=desde).count()
        if n:
            itens.append({'id': f'm{int(agora.timestamp())}', 'titulo': f'{n} nova(s) mensagem(ns) no WhatsApp',
                          'texto': 'Abra as conversas para responder.', 'url': '/notificacoes/conversas/'})
    return JsonResponse({'agora': agora.timestamp(), 'itens': itens})


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
