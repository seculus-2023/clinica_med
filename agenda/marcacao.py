"""Fluxo de marcação de consulta: especialidade -> médico (com grade) -> tipo -> semana com horários livres.

Usado na tela pública (paciente) e na tela interna da recepção.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from cadastros.models import Especialidade, HorarioAtendimento, Medico, TipoAtendimento

from .disponibilidade import horarios_livres

DIAS_CURTOS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']


def grade_medico(horarios):
    """[(dia_idx, 'Seg', ['08:00-12:00', ...]), ...] para os 7 dias."""
    por_dia = {i: [] for i in range(7)}
    for h in horarios:
        por_dia[h.dia_semana].append(f'{h.inicio:%H:%M}-{h.fim:%H:%M}')
    return [(i, DIAS_CURTOS[i], por_dia[i]) for i in range(7)]


def grade_completa(clinica, publico=False, especialidade=None):
    """Grade semanal de todos os médicos da clínica."""
    medicos = Medico.objects.filter(clinica=clinica, ativo=True).prefetch_related('especialidades', 'horarios')
    if publico:
        medicos = medicos.filter(agenda_online=True)
    if especialidade:
        medicos = medicos.filter(Q(especialidades=especialidade) | Q(especialidades__isnull=True))
    linhas = []
    for m in medicos.distinct():
        hs = sorted(m.horarios.all(), key=lambda h: (h.dia_semana, h.inicio))
        if publico and not hs:
            continue
        horas = sum(h.minutos for h in hs) / 60
        linhas.append({'medico': m, 'grade': grade_medico(hs), 'horas': horas,
                       'especialidades': ', '.join(e.nome for e in m.especialidades.all()) or 'Geral'})
    return linhas


def _medicos_base(clinica, publico):
    qs = Medico.objects.filter(clinica=clinica, ativo=True, horarios__isnull=False).distinct()
    return qs.filter(agenda_online=True) if publico else qs


def _tipos_base(clinica, publico):
    qs = TipoAtendimento.objects.filter(clinica=clinica, ativo=True)
    return qs.filter(agendamento_online=True) if publico else qs


def contexto(clinica, params, publico=True):
    medicos_base = _medicos_base(clinica, publico).prefetch_related('especialidades', 'horarios')
    tipos_base = _tipos_base(clinica, publico)

    # 1) especialidades com pelo menos um médico com grade e um tipo de atendimento
    esp_ids = set()
    tem_sem_esp = any(not m.especialidades.exists() for m in medicos_base)
    for m in medicos_base:
        esp_ids.update(e.pk for e in m.especialidades.all())
    especialidades = list(Especialidade.objects.filter(clinica=clinica, ativo=True, pk__in=esp_ids)) if not \
        tem_sem_esp else list(Especialidade.objects.filter(clinica=clinica, ativo=True))
    especialidades = [e for e in especialidades if tipos_base.filter(
        Q(especialidade=e) | Q(especialidade__isnull=True)).exists()]
    esp = next((e for e in especialidades if str(e.pk) == params.get('esp')), None)
    if not esp and len(especialidades) == 1:
        esp = especialidades[0]

    # 2) médicos da especialidade, com a grade semanal
    medicos = []
    if esp:
        for m in medicos_base:
            ids = {e.pk for e in m.especialidades.all()}
            if not ids or esp.pk in ids:
                medicos.append({'m': m, 'grade': grade_medico(sorted(m.horarios.all(),
                                                                     key=lambda h: (h.dia_semana, h.inicio)))})
    medico = next((x['m'] for x in medicos if str(x['m'].pk) == params.get('medico')), None)
    if not medico and len(medicos) == 1:
        medico = medicos[0]['m']

    # 3) tipos de atendimento da especialidade
    tipos = list(tipos_base.filter(Q(especialidade=esp) | Q(especialidade__isnull=True))) if esp else []
    tipo = next((t for t in tipos if str(t.pk) == params.get('tipo')), None)
    if not tipo and len(tipos) == 1:
        tipo = tipos[0]

    # 4) semana com horários livres
    hoje = timezone.localdate()
    try:
        sem = max(0, int(params.get('sem', 0)))
    except ValueError:
        sem = 0
    limite_dias = clinica.online_dias if publico else 120
    sem = min(sem, limite_dias // 7)
    inicio = hoje + timedelta(days=7 * sem)
    semana, total_livres = [], 0
    if medico and tipo:
        antecedencia = None if publico else 0
        for i in range(7):
            d = inicio + timedelta(days=i)
            livres = horarios_livres(clinica, medico, tipo, d, antecedencia) if (d - hoje).days <= limite_dias else []
            total_livres += len(livres)
            semana.append({'data': d, 'dia': DIAS_CURTOS[d.weekday()], 'livres': livres})
    return {
        'especialidades': especialidades, 'esp': esp, 'medicos': medicos, 'medico': medico, 'tipos': tipos,
        'tipo': tipo, 'semana': semana, 'sem': sem, 'sem_ant': sem - 1 if sem > 0 else None,
        'sem_prox': sem + 1 if (sem + 1) * 7 <= limite_dias else None, 'total_livres': total_livres,
        'semana_ini': inicio, 'semana_fim': inicio + timedelta(days=6), 'publico': publico,
    }
