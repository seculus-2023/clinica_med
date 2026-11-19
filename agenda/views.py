from datetime import datetime, timedelta

from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from cadastros.models import Medico
from contas.crud import Crud, moeda
from contas.permissoes import acesso, medico_restrito, tem_permissao

from .forms import AgendamentoForm, BloqueioForm, ListaEsperaForm, PacoteForm, RecursoForm
from .models import Agendamento, BloqueioAgenda, ListaEspera, PacoteSessao
from .services import mudar_status


def _agendamentos(request):
    qs = Agendamento.objects.filter(clinica=request.clinica).select_related('paciente', 'medico', 'tipo', 'pacote')
    med = medico_restrito(request)
    if med:
        qs = qs.filter(medico=med)
    return qs


@acesso('agenda')
def calendario(request):
    medicos = Medico.objects.filter(clinica=request.clinica, ativo=True)
    med = medico_restrito(request)
    if med:
        medicos = medicos.filter(pk=med.pk)
    from .models import Recurso
    return render(request, 'agenda/calendario.html', {
        'medicos': medicos, 'status': Agendamento.STATUS, 'cores': Agendamento.CORES,
        'recursos': Recurso.objects.filter(clinica=request.clinica, ativo=True),
        'medico_sel': request.GET.get('medico', '')})


@acesso('agenda', 'editar')
def marcar(request):
    """Tela de marcação de consulta da recepção: especialidade -> médico -> tipo -> horário livre."""
    from django.conf import settings

    from . import marcacao
    ctx = marcacao.contexto(request.clinica, request.GET, publico=False)
    ctx['paciente_sel'] = request.GET.get('paciente', '')
    ctx['link_online'] = settings.SITE_URL + reverse('agenda:online', args=[request.clinica.codigo_publico])
    return render(request, 'agenda/marcar.html', ctx)


@acesso('agenda')
def grade(request):
    """Grade de horários de atendimento de todos os médicos."""
    from cadastros.models import Especialidade

    from . import marcacao
    esp = Especialidade.objects.filter(clinica=request.clinica, pk=request.GET.get('esp') or 0).first()
    return render(request, 'agenda/grade.html', {
        'linhas': marcacao.grade_completa(request.clinica, especialidade=esp), 'dias': marcacao.DIAS_CURTOS,
        'especialidades': Especialidade.objects.filter(clinica=request.clinica, ativo=True), 'esp': esp,
        'pode_editar': tem_permissao(request, 'cadastros', 'editar')})


@acesso('agenda')
def eventos(request):
    ini = parse_datetime(request.GET.get('start', '')) or timezone.now() - timedelta(days=31)
    fim = parse_datetime(request.GET.get('end', '')) or timezone.now() + timedelta(days=31)
    qs = _agendamentos(request).filter(inicio__lt=fim, fim__gt=ini)
    if request.GET.get('medico'):
        qs = qs.filter(medico_id=request.GET['medico'])
    if request.GET.get('recurso'):
        qs = qs.filter(recurso_id=request.GET['recurso'])
    if request.GET.get('ocultar_cancelados') == '1':
        qs = qs.exclude(status='cancelado')
    dados = []
    for a in qs:
        sessao = f' • sessão {a.numero_sessao}/{a.pacote.quantidade}' if a.pacote_id else ''
        dados.append({
            'id': a.pk, 'title': f'{a.paciente.nome} ({a.tipo.nome}){sessao}',
            'start': a.inicio.isoformat(), 'end': a.fim.isoformat(),
            'backgroundColor': a.cor, 'borderColor': a.medico.cor,
            'url': reverse('agenda:detalhe', args=[a.pk]),
            'extendedProps': {'status': a.get_status_display(), 'medico': a.medico.nome,
                              'recurso': a.recurso.nome if a.recurso_id else ''},
        })
    return JsonResponse(dados, safe=False)


@acesso('agenda')
def dia(request):
    data = parse_date(request.GET.get('data', '')) or timezone.localdate()
    tz = timezone.get_current_timezone()
    ini = timezone.make_aware(datetime.combine(data, datetime.min.time()), tz)
    qs = _agendamentos(request).filter(inicio__gte=ini, inicio__lt=ini + timedelta(days=1))
    if request.GET.get('medico'):
        qs = qs.filter(medico_id=request.GET['medico'])
    medicos = Medico.objects.filter(clinica=request.clinica, ativo=True)
    resumo = {s: 0 for s, _ in Agendamento.STATUS}
    for a in qs:
        resumo[a.status] += 1
    return render(request, 'agenda/dia.html', {
        'data': data, 'anterior': data - timedelta(days=1), 'proximo': data + timedelta(days=1),
        'agendamentos': qs.order_by('inicio'), 'medicos': medicos, 'medico_sel': request.GET.get('medico', ''),
        'resumo': [(s, r, resumo[s], Agendamento.CORES[s]) for s, r in Agendamento.STATUS],
        'pode_editar': tem_permissao(request, 'agenda', 'editar')})


@acesso('agenda', 'editar')
def novo(request):
    inicial = {}
    if request.GET.get('inicio'):
        dt = parse_datetime(request.GET['inicio'])
        if dt:
            inicial['inicio'] = timezone.localtime(dt) if timezone.is_aware(dt) else dt
    for campo in ('paciente', 'medico', 'tipo', 'pacote'):
        if request.GET.get(campo):
            inicial[campo] = request.GET[campo]
    if inicial.get('pacote'):
        pac = PacoteSessao.objects.filter(pk=inicial['pacote'], clinica=request.clinica).first()
        if pac:
            inicial.update({'paciente': pac.paciente_id, 'tipo': pac.tipo_id})
            if pac.medico_id:
                inicial.setdefault('medico', pac.medico_id)
    form = AgendamentoForm(request.POST or None, initial=inicial, clinica=request.clinica,
                           medico_restrito=medico_restrito(request))
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            ag = form.save(commit=False)
            ag.clinica = request.clinica
            ag.criado_por = request.user
            if ag.status == 'confirmado':
                ag.confirmado_em, ag.confirmado_por = timezone.now(), 'recepcao'
            ag.save()
            criados = 1
            for semana in range(1, (form.cleaned_data.get('repetir') or 0) + 1):
                delta = timedelta(weeks=semana)
                conflito = Agendamento.objects.filter(
                    clinica=request.clinica, medico=ag.medico, inicio__lt=ag.fim + delta,
                    fim__gt=ag.inicio + delta).exclude(status__in=('cancelado', 'faltou')).exists()
                if conflito:
                    messages.warning(request, f'Semana {semana}: horário ocupado, não agendado.')
                    continue
                Agendamento.objects.create(
                    clinica=request.clinica, paciente=ag.paciente, medico=ag.medico, tipo=ag.tipo,
                    inicio=ag.inicio + delta, fim=ag.fim + delta, pacote=ag.pacote, convenio=ag.convenio,
                    valor=ag.valor, observacoes=ag.observacoes, notificar=ag.notificar, criado_por=request.user)
                criados += 1
        messages.success(request, f'{criados} agendamento(s) criado(s).' +
                         (' Paciente notificado.' if ag.notificar else ''))
        return redirect('agenda:detalhe', ag.pk)
    return render(request, 'agenda/form.html', {'form': form, 'titulo': 'Novo agendamento'})


@acesso('agenda', 'editar')
def editar(request, pk):
    ag = get_object_or_404(_agendamentos(request), pk=pk)
    form = AgendamentoForm(request.POST or None, instance=ag, clinica=request.clinica,
                           medico_restrito=medico_restrito(request))
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Agendamento atualizado.')
        return redirect('agenda:detalhe', ag.pk)
    return render(request, 'agenda/form.html', {'form': form, 'titulo': 'Editar agendamento', 'obj': ag})


@acesso('agenda')
def detalhe(request, pk):
    ag = get_object_or_404(_agendamentos(request), pk=pk)
    from documentos.models import Documento
    from financeiro.models import Lancamento
    from notificacoes.models import Notificacao
    from notificacoes.services import montar_mensagem
    return render(request, 'agenda/detalhe.html', {
        'ag': ag, 'status': Agendamento.STATUS,
        'lancamentos': Lancamento.objects.filter(agendamento=ag),
        'documentos': Documento.objects.filter(agendamento=ag),
        'notificacoes': Notificacao.objects.filter(agendamento=ag).order_by('-criado_em')[:20],
        'msg_whatsapp': montar_mensagem(ag, ag.clinica.msg_lembrete),
        'historico': Agendamento.objects.filter(paciente=ag.paciente).exclude(pk=ag.pk).select_related(
            'medico', 'tipo').order_by('-inicio')[:8],
        'pode_editar': tem_permissao(request, 'agenda', 'editar'),
        'pode_financeiro': tem_permissao(request, 'financeiro', 'editar'),
        'pode_documentos': tem_permissao(request, 'documentos', 'editar'),
    })


@acesso('agenda', 'editar')
@require_POST
def alterar_status(request, pk):
    ag = get_object_or_404(_agendamentos(request), pk=pk)
    novo = request.POST.get('status')
    if novo in dict(Agendamento.STATUS):
        mudar_status(ag, novo)
        messages.success(request, f'Status alterado para "{ag.get_status_display()}".')
    prox = request.POST.get('next', '')
    return redirect(prox if prox.startswith('/') else reverse('agenda:detalhe', args=[pk]))


@acesso('agenda', 'editar')
@require_POST
def reenviar(request, pk):
    from notificacoes.services import notificar_agendamento
    ag = get_object_or_404(_agendamentos(request), pk=pk)
    notificar_agendamento(ag, request.POST.get('evento', 'lembrete'), forcar=True)
    messages.success(request, 'Notificação enviada para o paciente (WhatsApp/e-mail).')
    return redirect('agenda:detalhe', pk)


@acesso('financeiro', 'editar')
@require_POST
def lancar_financeiro(request, pk):
    from financeiro.models import Lancamento
    ag = get_object_or_404(_agendamentos(request), pk=pk)
    if Lancamento.objects.filter(agendamento=ag).exclude(status='cancelado').exists():
        messages.warning(request, 'Este atendimento já possui lançamento financeiro.')
    elif not ag.valor:
        messages.warning(request, 'Atendimento sem valor a cobrar.')
    else:
        lan = Lancamento.objects.create(
            clinica=request.clinica, tipo='receita', descricao=f'{ag.tipo} - {ag.paciente}',
            categoria=Lancamento.categoria_padrao(request.clinica, 'receita', 'Atendimentos'),
            valor=ag.valor, vencimento=timezone.localdate(), paciente=ag.paciente, agendamento=ag,
            medico=ag.medico, criado_por=request.user)
        messages.success(request, f'Lançamento de {moeda(lan.valor)} criado no contas a receber.')
        return redirect('financeiro:lancamento_editar', lan.pk)
    return redirect('agenda:detalhe', pk)


# ------------- confirmação pública (link enviado ao paciente) -------------
def confirmar_publico(request, token):
    ag = get_object_or_404(Agendamento.objects.select_related('paciente', 'medico', 'tipo', 'clinica'), token=token)
    ag.clinica.ativar_fuso()
    resultado = None
    futuro = ag.inicio > timezone.now()
    if request.method == 'POST' and futuro and ag.status in ('agendado', 'confirmado'):
        acao = request.POST.get('acao')
        if acao == 'confirmar':
            mudar_status(ag, 'confirmado', origem='paciente')
            resultado = 'confirmado'
        elif acao == 'cancelar':
            mudar_status(ag, 'cancelado', origem='paciente')
            from contas.models import Lembrete
            Lembrete.objects.create(
                clinica=ag.clinica, titulo=f'Paciente cancelou: {ag.paciente}',
                mensagem=f'{ag} cancelado pelo paciente via link.', origem='sistema',
                link=reverse('agenda:detalhe', args=[ag.pk]))
            resultado = 'cancelado'
    return render(request, 'agenda/confirmar_publico.html', {'ag': ag, 'resultado': resultado, 'futuro': futuro})


@acesso('agenda')
def pacotes_paciente(request):
    qs = PacoteSessao.objects.filter(clinica=request.clinica, status='ativo',
                                     paciente_id=request.GET.get('paciente') or 0).select_related('tipo')
    return JsonResponse([{'id': p.pk, 'texto': f'{p.tipo} - {p.disponiveis} disponível(is) de {p.quantidade}',
                          'tipo': p.tipo_id} for p in qs], safe=False)


# ------------- Pacotes de sessões -------------
class PacoteCrud(Crud):
    model, form_class = PacoteSessao, PacoteForm
    modulo = 'sessoes'
    nome, nome_plural, url, icone = 'Pacote de sessões', 'Pacotes de sessões', 'agenda:pacote', 'bi-stack'
    descricao = 'Controle de sessões pagas antecipadamente (ex.: 10 sessões).'
    colunas = [('paciente', 'Paciente'), ('tipo', 'Atendimento'), ('quantidade', 'Sessões'), ('usadas', 'Usadas'),
               ('agendadas', 'Agendadas'), ('restantes', 'Restantes'), ('valor_total', 'Valor', 'moeda'),
               ('validade', 'Validade'), ('status', 'Status')]
    busca = ['paciente__nome', 'tipo__nome']
    filtros = [('status', 'Status', PacoteSessao.STATUS)]
    acoes_linha = [('agenda:pacote_detalhe', 'bi-eye', 'Detalhes')]

    @classmethod
    def queryset(cls, request):
        return PacoteSessao.objects.filter(clinica=request.clinica).select_related('paciente', 'tipo')


@acesso('sessoes', 'editar')
def pacote_novo(request):
    form = PacoteForm(request.POST or None, initial=request.GET.dict(), clinica=request.clinica)
    if request.method == 'POST' and form.is_valid():
        from financeiro.models import Lancamento
        with transaction.atomic():
            pac = form.save(commit=False)
            pac.clinica = request.clinica
            pac.valor_total = form.cleaned_data['valor_total']
            pac.save()
            d = form.cleaned_data
            if d.get('gerar_financeiro') and pac.valor_total:
                Lancamento.gerar_parcelas(
                    clinica=request.clinica, descricao=f'Pacote {pac.quantidade}x {pac.tipo} - {pac.paciente}',
                    total=pac.valor_total, parcelas=d.get('parcelas') or 1, primeiro_vencimento=pac.data_compra,
                    primeira_paga=d.get('ja_pago'), forma=d.get('forma_pagamento') or '', paciente=pac.paciente,
                    pacote=pac, usuario=request.user, medico=pac.medico)
        messages.success(request, 'Pacote cadastrado.')
        return redirect('agenda:pacote_detalhe', pac.pk)
    return render(request, 'form_simples.html', {'form': form, 'titulo': 'Novo pacote de sessões',
                                                 'voltar': 'agenda:pacote_list'})


@acesso('sessoes')
def pacote_detalhe(request, pk):
    pac = get_object_or_404(PacoteSessao.objects.select_related('paciente', 'tipo', 'medico'), pk=pk,
                            clinica=request.clinica)
    from financeiro.models import Lancamento
    ags = pac.agendamentos.select_related('medico').order_by('inicio')
    return render(request, 'agenda/pacote_detalhe.html', {
        'pac': pac, 'agendamentos': ags, 'lancamentos': Lancamento.objects.filter(pacote=pac),
        'pode_editar': tem_permissao(request, 'sessoes', 'editar'),
        'pode_agendar': tem_permissao(request, 'agenda', 'editar')})


class BloqueioCrud(Crud):
    model, form_class = BloqueioAgenda, BloqueioForm
    modulo = 'agenda'
    nome, nome_plural, url, icone = 'Bloqueio', 'Bloqueios de agenda', 'agenda:bloqueio', 'bi-slash-circle'
    descricao = 'Férias, feriados, reuniões: horários bloqueados não aceitam agendamentos (nem online).'
    colunas = [('inicio', 'Início'), ('fim', 'Fim'), ('medico', 'Profissional'), ('motivo', 'Motivo')]
    busca = ['motivo', 'medico__nome']


class EsperaCrud(Crud):
    model, form_class = ListaEspera, ListaEsperaForm
    modulo = 'agenda'
    nome, nome_plural, url, icone = ('Paciente na lista', 'Lista de espera (encaixes)', 'agenda:espera',
                                     'bi-hourglass-split')
    descricao = 'Quando um horário é cancelado, o sistema avisa a recepção sobre os pacientes compatíveis.'
    colunas = [('desde', 'Desde'), ('paciente', 'Paciente'), ('paciente__celular', 'Celular'),
               ('medico', 'Profissional'), ('tipo', 'Atendimento'), ('preferencia', 'Preferência'),
               ('prioridade', 'Prioridade'), ('status', 'Status')]
    busca = ['paciente__nome', 'preferencia']
    filtros = [('status', 'Status', ListaEspera.STATUS)]
    acoes_linha = [('agenda:espera_agendar', 'bi-calendar-plus', 'Agendar')]

    @classmethod
    def queryset(cls, request):
        return ListaEspera.objects.filter(clinica=request.clinica).select_related('paciente', 'medico', 'tipo')


@acesso('agenda', 'editar')
def espera_agendar(request, pk):
    e = get_object_or_404(ListaEspera, pk=pk, clinica=request.clinica)
    e.status = 'agendado'
    e.save(update_fields=['status', 'atualizado_em'])
    url = f"{reverse('agenda:novo')}?paciente={e.paciente_id}"
    if e.medico_id:
        url += f'&medico={e.medico_id}'
    if e.tipo_id:
        url += f'&tipo={e.tipo_id}'
    return redirect(url)


class RecursoCrud(Crud):
    from .models import Recurso as _R
    model, form_class = _R, RecursoForm
    modulo = 'agenda'
    nome, nome_plural, url, icone = 'Sala / equipamento', 'Salas e equipamentos', 'agenda:recurso', 'bi-door-open'
    descricao = 'Recursos reservados junto com o atendimento. Vincule ao tipo de atendimento para reservar automaticamente.'
    colunas = [('nome', 'Nome'), ('tipo', 'Tipo'), ('descricao', 'Descrição'), ('ativo', 'Ativo')]
    busca = ['nome']
