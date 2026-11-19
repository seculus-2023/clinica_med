import json
from datetime import timedelta

from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.shortcuts import redirect, render
from django.utils import timezone

from agenda.models import Agendamento, PacoteSessao
from cadastros.models import Paciente
from callcenter.models import ContatoPaciente
from contas.permissoes import acesso, medico_restrito, tem_permissao
from estoque.models import Produto
from financeiro.models import Lancamento


def inicio(request):
    if not request.user.is_authenticated:
        return redirect('contas:login')
    return redirect('painel:dashboard')


def erro_403(request, exception=None):
    return render(request, '403.html', status=403)


@acesso('dashboard')
def dashboard(request):
    c = request.clinica
    agora = timezone.localtime()
    hoje = agora.date()
    ini_dia = agora.replace(hour=0, minute=0, second=0, microsecond=0)
    ini_mes = hoje.replace(day=1)
    ags = Agendamento.objects.filter(clinica=c)
    med = medico_restrito(request)
    if med:
        ags = ags.filter(medico=med)
    ags_hoje = ags.filter(inicio__gte=ini_dia, inicio__lt=ini_dia + timedelta(days=1))
    st = dict(ags_hoje.values_list('status').annotate(n=Count('id')))
    ctx = {
        'hoje': hoje,
        'k_agenda': {
            'total': sum(v for k, v in st.items() if k != 'cancelado'),
            'confirmados': st.get('confirmado', 0), 'aguardando': st.get('aguardando', 0) + st.get(
                'em_atendimento', 0),
            'concluidos': st.get('concluido', 0), 'faltas': st.get('faltou', 0),
            'a_confirmar': st.get('agendado', 0),
        },
        'proximos': ags.filter(inicio__gte=timezone.now(), status__in=('agendado', 'confirmado')).select_related(
            'paciente', 'medico', 'tipo').order_by('inicio')[:8],
        'pacientes_ativos': Paciente.objects.filter(clinica=c, ativo=True).count(),
        'pacientes_novos': Paciente.objects.filter(clinica=c, criado_em__date__gte=ini_mes).count(),
        'pacotes_ativos': PacoteSessao.objects.filter(clinica=c, status='ativo').count(),
        'estoque_baixo': Produto.objects.filter(clinica=c, ativo=True, saldo__lte=F('estoque_minimo')).count(),
        'callcenter': ContatoPaciente.objects.filter(
            clinica=c, status__in=('pendente', 'em_andamento', 'sem_resposta'), data_prevista__lte=hoje).count(),
        'ver_financeiro': tem_permissao(request, 'financeiro'),
    }
    # pacotes com poucas sessões restantes (avisar renovação)
    ctx['pacotes_acabando'] = [p for p in PacoteSessao.objects.filter(clinica=c, status='ativo').select_related(
        'paciente', 'tipo')[:200] if p.restantes <= 2][:6]

    # gráfico: atendimentos dos últimos 30 dias
    ini30 = ini_dia - timedelta(days=29)
    por_dia = dict(ags.filter(inicio__gte=ini30, inicio__lt=ini_dia + timedelta(days=1)).exclude(
        status='cancelado').annotate(d=TruncDate('inicio')).values_list('d').annotate(n=Count('id')))
    dias = [hoje - timedelta(days=i) for i in range(29, -1, -1)]
    graf = {'dias': [d.strftime('%d/%m') for d in dias], 'atend': [por_dia.get(d, 0) for d in dias]}
    mes = ags.filter(inicio__date__gte=ini_mes)
    graf['status'] = [[dict(Agendamento.STATUS)[s], n, Agendamento.CORES[s]] for s, n in
                      mes.values_list('status').annotate(n=Count('id')).order_by('-n')]
    graf['medicos'] = [[m, n] for m, n in mes.exclude(status='cancelado').values_list('medico__nome').annotate(
        n=Count('id')).order_by('-n')[:8]]

    if ctx['ver_financeiro']:
        lan = Lancamento.objects.filter(clinica=c).exclude(status='cancelado')
        lm = lan.filter(vencimento__year=hoje.year, vencimento__month=hoje.month)

        def s(qs):
            return qs.aggregate(s=Sum('valor'))['s'] or 0
        ctx['k_fin'] = {
            'recebido': s(lm.filter(tipo='receita', status='pago')),
            'receber': s(lm.filter(tipo='receita', status='pendente')),
            'despesas': s(lm.filter(tipo='despesa')),
            'atrasados': s(lan.filter(tipo='receita', status='pendente', vencimento__lt=hoje)),
        }
        ctx['k_fin']['saldo'] = ctx['k_fin']['recebido'] - s(lm.filter(tipo='despesa', status='pago'))
        ini6 = (ini_mes - timedelta(days=150)).replace(day=1)
        meses = {}
        for r in lan.filter(status='pago', vencimento__gte=ini6, vencimento__lte=hoje).annotate(
                m=TruncMonth('vencimento')).values('m', 'tipo').annotate(s=Sum('valor')):
            meses.setdefault(r['m'], {'receita': 0, 'despesa': 0})[r['tipo']] = float(r['s'])
        chaves = sorted(meses)
        graf['meses'] = [m.strftime('%m/%Y') for m in chaves]
        graf['receitas'] = [meses[m]['receita'] for m in chaves]
        graf['despesas'] = [meses[m]['despesa'] for m in chaves]
    ctx['graf'] = json.dumps(graf)
    return render(request, 'painel/dashboard.html', ctx)


@acesso(None)
def busca(request):
    q = request.GET.get('q', '').strip()
    res = {}
    if len(q) >= 2:
        if tem_permissao(request, 'cadastros'):
            res['pacientes'] = Paciente.objects.filter(clinica=request.clinica).filter(
                Q(nome__icontains=q) | Q(cpf__icontains=q) | Q(celular__icontains=q))[:15]
        if tem_permissao(request, 'agenda'):
            res['agendamentos'] = Agendamento.objects.filter(clinica=request.clinica, paciente__nome__icontains=q
                                                             ).select_related('paciente', 'medico').order_by(
                '-inicio')[:15]
    return render(request, 'painel/busca.html', {'q': q, 'res': res})
