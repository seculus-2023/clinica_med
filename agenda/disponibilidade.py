"""Cálculo de horários livres (agendamento online e taxa de ocupação)."""
from datetime import datetime, timedelta

from django.utils import timezone

from cadastros.models import HorarioAtendimento

from .models import Agendamento, BloqueioAgenda


def horarios_livres(clinica, medico, tipo, data, antecedencia_horas=None):
    tz = timezone.get_current_timezone()
    dur = timedelta(minutes=tipo.duracao_minutos or 30)
    if antecedencia_horas is None:
        antecedencia_horas = clinica.online_antecedencia_horas
    limite = timezone.now() + timedelta(hours=antecedencia_horas)
    ini_dia = timezone.make_aware(datetime.combine(data, datetime.min.time()), tz)
    ocupados = list(Agendamento.objects.filter(
        clinica=clinica, medico=medico, inicio__lt=ini_dia + timedelta(days=1), fim__gt=ini_dia).exclude(
        status__in=('cancelado', 'faltou')).values_list('inicio', 'fim'))
    bloqueios = list(BloqueioAgenda.objects.filter(
        clinica=clinica, inicio__lt=ini_dia + timedelta(days=1), fim__gt=ini_dia).filter(
        medico__in=[medico]).values_list('inicio', 'fim')) + list(BloqueioAgenda.objects.filter(
            clinica=clinica, medico__isnull=True, inicio__lt=ini_dia + timedelta(days=1), fim__gt=ini_dia
        ).values_list('inicio', 'fim'))
    livres = []
    for h in HorarioAtendimento.objects.filter(clinica=clinica, medico=medico, dia_semana=data.weekday()):
        t = timezone.make_aware(datetime.combine(data, h.inicio), tz)
        fim_turno = timezone.make_aware(datetime.combine(data, h.fim), tz)
        while t + dur <= fim_turno:
            f = t + dur
            if t >= limite and not any(a < f and b > t for a, b in ocupados + bloqueios):
                livres.append(t)
            t += dur
    return livres


def minutos_disponiveis(clinica, ini, fim, medico=None):
    """Minutos de grade de atendimento entre duas datas (para taxa de ocupação)."""
    horarios = HorarioAtendimento.objects.filter(clinica=clinica)
    if medico:
        horarios = horarios.filter(medico=medico)
    por_dia = {}
    for h in horarios:
        por_dia[h.dia_semana] = por_dia.get(h.dia_semana, 0) + h.minutos
    total, d = 0, ini
    while d <= fim:
        total += por_dia.get(d.weekday(), 0)
        d += timedelta(days=1)
    return total
