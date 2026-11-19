"""Relatórios com filtro por período, impressão e exportação CSV."""
import csv
from datetime import datetime, timedelta

from django.db.models import Avg, Count, F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.dateparse import parse_date

from agenda.models import Agendamento, PacoteSessao
from cadastros.models import Medico, Paciente
from callcenter.models import ContatoPaciente
from contas.crud import moeda
from contas.permissoes import acesso, medico_restrito, tem_permissao
from estoque.models import MovimentoEstoque, Produto
from financeiro.models import FORMAS_PAGAMENTO, Lancamento

RELATORIOS = [
    ('indicadores', 'Indicadores gerenciais (BI)', 'bi-speedometer2', 'relatorios'),
    ('repasse', 'Repasse médico (split)', 'bi-people', 'financeiro'),
    ('convenios', 'Faturamento por convênio', 'bi-building-check', 'financeiro'),
    ('nps', 'Pesquisa de satisfação (NPS)', 'bi-star', 'callcenter'),
    ('agendamentos', 'Agendamentos por período', 'bi-calendar3', 'agenda'),
    ('produtividade', 'Produtividade por profissional', 'bi-person-badge', 'agenda'),
    ('tipos', 'Atendimentos por tipo', 'bi-tags', 'agenda'),
    ('faltas', 'Faltas e cancelamentos', 'bi-calendar-x', 'agenda'),
    ('financeiro', 'Lançamentos financeiros', 'bi-cash-coin', 'financeiro'),
    ('categorias', 'Receitas e despesas por categoria', 'bi-pie-chart', 'financeiro'),
    ('inadimplencia', 'Inadimplência (receitas vencidas)', 'bi-exclamation-triangle', 'financeiro'),
    ('sessoes', 'Pacotes de sessões', 'bi-stack', 'sessoes'),
    ('pacientes', 'Pacientes cadastrados', 'bi-people', 'cadastros'),
    ('aniversariantes', 'Aniversariantes do período', 'bi-gift', 'cadastros'),
    ('estoque', 'Posição de estoque', 'bi-box-seam', 'estoque'),
    ('movimentos', 'Movimentações de estoque', 'bi-arrow-left-right', 'estoque'),
    ('callcenter', 'Call center / satisfação', 'bi-headset', 'callcenter'),
]


def _dt(d):
    return timezone.make_aware(datetime.combine(d, datetime.min.time()), timezone.get_current_timezone())


def _l(dt):
    return timezone.localtime(dt).strftime('%d/%m/%Y %H:%M') if dt else ''


def _gerar(tipo, c, ini, fim, request):
    ini_dt, fim_dt = _dt(ini), _dt(fim + timedelta(days=1))
    medico = request.GET.get('medico')
    ags = Agendamento.objects.filter(clinica=c, inicio__gte=ini_dt, inicio__lt=fim_dt).select_related(
        'paciente', 'medico', 'tipo')
    restrito = medico_restrito(request)
    if restrito:
        ags = ags.filter(medico=restrito)
    if medico:
        ags = ags.filter(medico_id=medico)
    total = None
    if tipo == 'indicadores':
        return _indicadores(c, ini, fim, ags, request)
    if tipo == 'repasse':
        return _repasse(c, ini, fim, medico)
    if tipo == 'convenios':
        cab = ['Convênio', 'Atendimentos concluídos', 'Valor produzido', 'Ticket médio']
        linhas = []
        for r in ags.filter(status='concluido').values('paciente__convenio', 'convenio').annotate(
                n=Count('id'), v=Sum('valor')).order_by('-v'):
            nome = r['paciente__convenio'] if r['convenio'] and r['paciente__convenio'] else (
                'Convênio (não informado)' if r['convenio'] else 'Particular')
            linhas.append([nome, r['n'], moeda(r['v'] or 0), moeda((r['v'] or 0) / r['n'] if r['n'] else 0)])
        return cab, linhas, None
    if tipo == 'nps':
        from agenda.models import AvaliacaoNPS
        avs = AvaliacaoNPS.objects.filter(clinica=c, criado_em__gte=ini_dt, criado_em__lt=fim_dt).select_related(
            'agendamento__paciente', 'agendamento__medico')
        if medico:
            avs = avs.filter(agendamento__medico_id=medico)
        cab = ['Data', 'Paciente', 'Profissional', 'Nota (0-10)', 'Profissional', 'Recepção', 'Classificação',
               'Comentário']
        linhas = [[timezone.localtime(a.criado_em).strftime('%d/%m/%Y'), a.agendamento.paciente.nome,
                   a.agendamento.medico.nome, a.nota, a.nota_medico if a.nota_medico is not None else '',
                   a.nota_recepcao if a.nota_recepcao is not None else '', a.classificacao, a.comentario]
                  for a in avs]
        n = len(linhas)
        if n:
            prom = sum(1 for a in avs if a.nota >= 9)
            detr = sum(1 for a in avs if a.nota <= 6)
            total = ['', f'{n} resposta(s)', '', f'NPS = {round((prom - detr) * 100 / n)}', '', '',
                     f'{prom} promotores / {detr} detratores', '']
        return cab, linhas, total
    if tipo == 'agendamentos':
        cab = ['Data/hora', 'Paciente', 'Profissional', 'Tipo', 'Status', 'Pacote', 'Valor']
        linhas = [[_l(a.inicio), a.paciente.nome, a.medico.nome, a.tipo.nome, a.get_status_display(),
                   'Sim' if a.pacote_id else '', moeda(a.valor)] for a in ags.order_by('inicio')]
        total = ['Total', f'{len(linhas)} agendamento(s)', '', '', '', '',
                 moeda(sum((a.valor or 0) for a in ags if a.status not in ('cancelado', 'faltou')))]
    elif tipo == 'produtividade':
        cab = ['Profissional', 'Agendados', 'Concluídos', 'Faltas', 'Cancelados', 'Taxa de comparecimento',
               'Valor produzido']
        linhas = []
        for r in ags.values('medico__nome').annotate(
                n=Count('id'), conc=Count('id', filter=Q(status='concluido')),
                falt=Count('id', filter=Q(status='faltou')), canc=Count('id', filter=Q(status='cancelado')),
                valor=Sum('valor', filter=Q(status='concluido'))).order_by('-n'):
            base = r['n'] - r['canc']
            taxa = f"{(r['conc'] * 100 / base):.0f}%" if base else '-'
            linhas.append([r['medico__nome'], r['n'], r['conc'], r['falt'], r['canc'], taxa, moeda(r['valor'] or 0)])
    elif tipo == 'tipos':
        cab = ['Tipo de atendimento', 'Quantidade', 'Concluídos', 'Valor total (concluídos)']
        linhas = [[r['tipo__nome'], r['n'], r['conc'], moeda(r['v'] or 0)] for r in ags.exclude(
            status='cancelado').values('tipo__nome').annotate(n=Count('id'), conc=Count(
                'id', filter=Q(status='concluido')), v=Sum('valor', filter=Q(status='concluido'))).order_by('-n')]
    elif tipo == 'faltas':
        cab = ['Data/hora', 'Paciente', 'Celular', 'Profissional', 'Status']
        linhas = [[_l(a.inicio), a.paciente.nome, a.paciente.celular, a.medico.nome, a.get_status_display()]
                  for a in ags.filter(status__in=('faltou', 'cancelado')).order_by('inicio')]
    elif tipo == 'financeiro':
        lan = Lancamento.objects.filter(clinica=c, vencimento__range=(ini, fim)).select_related('categoria',
                                                                                                'paciente')
        if request.GET.get('tipo_lanc'):
            lan = lan.filter(tipo=request.GET['tipo_lanc'])
        formas = dict(FORMAS_PAGAMENTO)
        cab = ['Vencimento', 'Tipo', 'Descrição', 'Categoria', 'Paciente/Fornecedor', 'Situação', 'Pagamento',
               'Forma', 'Valor']
        linhas = [[x.vencimento.strftime('%d/%m/%Y'), x.get_tipo_display(), x.descricao, str(x.categoria or ''),
                   (x.paciente.nome if x.paciente else x.fornecedor), x.situacao,
                   x.data_pagamento.strftime('%d/%m/%Y') if x.data_pagamento else '',
                   formas.get(x.forma_pagamento, ''), moeda(x.valor)] for x in lan.order_by('vencimento')]
        at = lan.exclude(status='cancelado')
        rec = at.filter(tipo='receita').aggregate(s=Sum('valor'))['s'] or 0
        desp = at.filter(tipo='despesa').aggregate(s=Sum('valor'))['s'] or 0
        total = ['', '', f'Receitas {moeda(rec)} | Despesas {moeda(desp)}', '', '', '', '', 'Resultado',
                 moeda(rec - desp)]
    elif tipo == 'categorias':
        cab = ['Tipo', 'Categoria', 'Previsto', 'Realizado (pago)']
        linhas = [[('Receita' if r['tipo'] == 'receita' else 'Despesa'), r['categoria__nome'] or 'Sem categoria',
                   moeda(r['prev']), moeda(r['real'] or 0)] for r in Lancamento.objects.filter(
            clinica=c, vencimento__range=(ini, fim)).exclude(status='cancelado').values(
            'tipo', 'categoria__nome').annotate(prev=Sum('valor'), real=Sum('valor', filter=Q(status='pago'))
                                                ).order_by('tipo', '-prev')]
    elif tipo == 'inadimplencia':
        hoje = timezone.localdate()
        lan = Lancamento.objects.filter(clinica=c, tipo='receita', status='pendente', vencimento__lt=hoje
                                        ).select_related('paciente').order_by('vencimento')
        cab = ['Vencimento', 'Dias em atraso', 'Paciente', 'Celular', 'Descrição', 'Valor']
        linhas = [[x.vencimento.strftime('%d/%m/%Y'), (hoje - x.vencimento).days,
                   x.paciente.nome if x.paciente else '-', x.paciente.celular if x.paciente else '', x.descricao,
                   moeda(x.valor)] for x in lan]
        total = ['', '', '', '', 'Total', moeda(lan.aggregate(s=Sum('valor'))['s'] or 0)]
    elif tipo == 'sessoes':
        cab = ['Compra', 'Paciente', 'Atendimento', 'Sessões', 'Usadas', 'Agendadas', 'Restantes', 'Validade',
               'Status', 'Valor']
        pacs = PacoteSessao.objects.filter(clinica=c, data_compra__range=(ini, fim)).select_related('paciente',
                                                                                                    'tipo')
        if request.GET.get('todos_pacotes'):
            pacs = PacoteSessao.objects.filter(clinica=c, status='ativo').select_related('paciente', 'tipo')
        linhas = [[p.data_compra.strftime('%d/%m/%Y'), p.paciente.nome, p.tipo.nome, p.quantidade, p.usadas,
                   p.agendadas, p.restantes, p.validade.strftime('%d/%m/%Y') if p.validade else '',
                   p.get_status_display(), moeda(p.valor_total)] for p in pacs]
    elif tipo == 'pacientes':
        cab = ['Nome', 'CPF', 'Nascimento', 'Celular', 'E-mail', 'Convênio', 'Cadastro', 'Atendimentos']
        pac = Paciente.objects.filter(clinica=c, criado_em__gte=ini_dt, criado_em__lt=fim_dt).annotate(
            n=Count('agendamentos', filter=Q(agendamentos__status='concluido')))
        linhas = [[p.nome, p.cpf, p.data_nascimento.strftime('%d/%m/%Y') if p.data_nascimento else '', p.celular,
                   p.email, p.convenio, timezone.localtime(p.criado_em).strftime('%d/%m/%Y'), p.n] for p in pac]
    elif tipo == 'aniversariantes':
        cab = ['Dia', 'Nome', 'Idade', 'Celular', 'E-mail']
        linhas = []
        for p in Paciente.objects.filter(clinica=c, ativo=True, data_nascimento__isnull=False):
            for ano in {ini.year, fim.year}:
                try:
                    aniv = p.data_nascimento.replace(year=ano)
                except ValueError:
                    aniv = p.data_nascimento.replace(year=ano, day=28)
                if ini <= aniv <= fim:
                    linhas.append([aniv.strftime('%d/%m'), p.nome, ano - p.data_nascimento.year, p.celular, p.email])
        linhas.sort(key=lambda r: r[0][3:] + r[0][:2])
    elif tipo == 'estoque':
        cab = ['Produto', 'Categoria', 'Saldo', 'Mínimo', 'Situação', 'Custo médio', 'Valor em estoque']
        prods = Produto.objects.filter(clinica=c, ativo=True)
        linhas = [[p.nome, p.get_categoria_display(), f'{p.saldo} {p.unidade}', p.estoque_minimo,
                   'ABAIXO DO MÍNIMO' if p.abaixo_minimo else 'OK', moeda(p.custo_medio), moeda(p.valor_estoque)]
                  for p in prods]
        total = ['Total', '', '', '', '', '', moeda(sum(p.valor_estoque for p in prods))]
    elif tipo == 'movimentos':
        cab = ['Data', 'Produto', 'Tipo', 'Quantidade', 'Custo unit.', 'Lote', 'Validade', 'Paciente', 'Motivo']
        linhas = [[m.data.strftime('%d/%m/%Y'), m.produto.nome, m.get_tipo_display(), m.quantidade,
                   moeda(m.custo_unitario), m.lote, m.validade.strftime('%d/%m/%Y') if m.validade else '',
                   m.paciente.nome if m.paciente else '', m.motivo]
                  for m in MovimentoEstoque.objects.filter(clinica=c, data__range=(ini, fim)).select_related(
                      'produto', 'paciente')]
    elif tipo == 'callcenter':
        cc = ContatoPaciente.objects.filter(clinica=c, data_prevista__range=(ini, fim)).select_related(
            'paciente', 'medico', 'responsavel')
        cab = ['Data', 'Paciente', 'Motivo', 'Profissional', 'Status', 'Tentativas', 'Satisfação', 'Responsável']
        linhas = [[x.data_prevista.strftime('%d/%m/%Y'), x.paciente.nome, x.get_motivo_display(),
                   str(x.medico or ''), x.get_status_display(), x.tentativas, x.satisfacao or '',
                   str(x.responsavel or '')] for x in cc]
        media = cc.aggregate(m=Avg('satisfacao'))['m']
        total = ['', f'{len(linhas)} contato(s)', '', '', '', '', f'Média {media:.1f}' if media else '-', '']
    else:
        cab, linhas = [], []
    return cab, linhas, total


def _pct(a, b):
    return f'{a * 100 / b:.1f}%' if b else '-'


def _indicadores(c, ini, fim, ags, request):
    from agenda.disponibilidade import minutos_disponiveis
    total = ags.count()
    st = dict(ags.values_list('status').annotate(n=Count('id')))
    validos = total - st.get('cancelado', 0)
    concl = st.get('concluido', 0)
    faltas = st.get('faltou', 0)
    minutos_ag = sum(int((f - i).total_seconds() // 60) for i, f in ags.exclude(
        status__in=('cancelado', 'faltou')).values_list('inicio', 'fim'))
    med = request.GET.get('medico') or None
    disp = minutos_disponiveis(c, ini, fim, med)
    receitas = Lancamento.objects.filter(clinica=c, tipo='receita', status='pago', data_pagamento__range=(ini, fim))
    rec = receitas.aggregate(s=Sum('valor'))['s'] or 0
    novos = Paciente.objects.filter(clinica=c, criado_em__date__range=(ini, fim))
    linhas = [
        ['Agendamentos no período', total],
        ['Taxa de ocupação da agenda', _pct(minutos_ag, disp) + (f' ({minutos_ag // 60}h de {disp // 60}h de grade)'
                                                                 if disp else ' (cadastre os horários de atendimento)')],
        ['Atendimentos concluídos', concl],
        ['Taxa de comparecimento', _pct(concl, validos)],
        ['Índice de faltas (no-show)', f'{_pct(faltas, validos)} ({faltas})'],
        ['Cancelamentos', f"{_pct(st.get('cancelado', 0), total)} ({st.get('cancelado', 0)})"],
        ['Confirmados pelo paciente (link/check-in)', ags.filter(confirmado_por='paciente').count()],
        ['Agendamentos online', ags.filter(origem='online').count()],
        ['Receita recebida', moeda(rec)],
        ['Ticket médio (receita / atendimento concluído)', moeda(rec / concl if concl else 0)],
        ['Novos pacientes', novos.count()],
    ]
    nomes = dict(Paciente.ORIGENS)
    for r in novos.values('origem').annotate(n=Count('id')).order_by('-n'):
        linhas.append([f'  Origem: {nomes.get(r["origem"]) or "Não informada"}', r['n']])
    from agenda.models import AvaliacaoNPS
    avs = list(AvaliacaoNPS.objects.filter(clinica=c, criado_em__date__range=(ini, fim)).values_list('nota', flat=True))
    if avs:
        linhas.append(['NPS', round((sum(1 for n in avs if n >= 9) - sum(1 for n in avs if n <= 6)) * 100 / len(avs))])
    return ['Indicador', 'Valor'], linhas, None


def _repasse(c, ini, fim, medico):
    taxas = {'credito': c.taxa_credito, 'debito': c.taxa_debito}
    lan = Lancamento.objects.filter(clinica=c, tipo='receita', status='pago', data_pagamento__range=(ini, fim),
                                    medico__isnull=False).select_related('medico')
    if medico:
        lan = lan.filter(medico_id=medico)
    por = {}
    for x in lan:
        bruto = x.valor_pago or x.valor
        taxa = (bruto * taxas.get(x.forma_pagamento, 0) / 100).quantize(bruto)
        r = por.setdefault(x.medico, {'n': 0, 'bruto': 0, 'taxa': 0})
        r['n'] += 1
        r['bruto'] += bruto
        r['taxa'] += taxa
    cab = ['Profissional', 'Recebimentos', 'Valor bruto', 'Taxas de cartão', 'Valor líquido', '% repasse',
           'Repasse ao profissional', 'Fica para a clínica']
    linhas, tot = [], 0
    for m, r in sorted(por.items(), key=lambda i: -i[1]['bruto']):
        liquido = r['bruto'] - r['taxa']
        rep = (liquido * m.percentual_repasse / 100).quantize(liquido) if liquido else 0
        tot += rep
        linhas.append([m.nome, r['n'], moeda(r['bruto']), moeda(r['taxa']), moeda(liquido),
                       f'{m.percentual_repasse}%', moeda(rep), moeda(liquido - rep)])
    return cab, linhas, ['Total', '', '', '', '', '', moeda(tot), '']


@acesso('relatorios')
def relatorios(request):
    disponiveis = [r for r in RELATORIOS if tem_permissao(request, r[3])]
    tipo = request.GET.get('tipo')
    hoje = timezone.localdate()
    ini = parse_date(request.GET.get('de', '')) or hoje.replace(day=1)
    fim = parse_date(request.GET.get('ate', '')) or hoje
    ctx = {'relatorios': disponiveis, 'tipo': tipo, 'de': ini, 'ate': fim,
           'medicos': Medico.objects.filter(clinica=request.clinica), 'medico_sel': request.GET.get('medico', '')}
    info = next((r for r in disponiveis if r[0] == tipo), None)
    if info:
        cab, linhas, total = _gerar(tipo, request.clinica, ini, fim, request)
        if request.GET.get('formato') == 'csv':
            resp = HttpResponse(content_type='text/csv; charset=utf-8')
            resp['Content-Disposition'] = f'attachment; filename="relatorio_{tipo}_{ini}_{fim}.csv"'
            resp.write('﻿')
            w = csv.writer(resp, delimiter=';')
            w.writerow(cab)
            w.writerows(linhas)
            if total:
                w.writerow(total)
            return resp
        ctx.update({'info': info, 'cab': cab, 'linhas': linhas, 'total': total,
                    'params': request.GET.urlencode()})
    return render(request, 'painel/relatorios.html', ctx)
