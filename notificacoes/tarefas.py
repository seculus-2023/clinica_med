"""Rotinas periódicas: lembretes a pacientes, médicos e usuários do sistema."""
import logging
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.db.models import F
from django.urls import reverse
from django.utils import timezone

from contas.models import Clinica, Lembrete

from .services import enfileirar, notificar_agendamento

log = logging.getLogger('notificacoes')


def _inicio_dia(data):
    return timezone.make_aware(datetime.combine(data, datetime.min.time()), timezone.get_current_timezone())


def _lembrete_unico_hoje(clinica, origem, titulo, mensagem='', usuario=None, link=''):
    """Cria um lembrete in-app por dia/origem/usuário (evita duplicar)."""
    hoje = timezone.localdate()
    if Lembrete.objects.filter(clinica=clinica, origem=origem, usuario=usuario,
                               criado_em__gte=_inicio_dia(hoje)).exists():
        return None
    return Lembrete.objects.create(clinica=clinica, origem=origem, titulo=titulo, mensagem=mensagem,
                                   usuario=usuario, link=link, data_hora=timezone.now())


def lembretes_pacientes(clinica):
    from agenda.models import Agendamento
    agora = timezone.now()
    qs = Agendamento.objects.filter(
        clinica=clinica, status__in=('agendado', 'confirmado'), lembrete_enviado=False, notificar=True,
        inicio__gt=agora, inicio__lte=agora + timedelta(hours=clinica.lembrete_horas_antes)
    ).select_related('paciente', 'medico', 'tipo', 'clinica')
    n = 0
    for ag in qs:
        notificar_agendamento(ag, 'lembrete')
        Agendamento.objects.filter(pk=ag.pk).update(lembrete_enviado=True)
        n += 1
    return n


def agenda_diaria_medicos(clinica):
    from agenda.models import Agendamento
    from cadastros.models import Medico
    if timezone.localtime().hour < 6:
        return 0
    hoje = timezone.localdate()
    ini = _inicio_dia(hoje)
    n = 0
    for med in Medico.objects.filter(clinica=clinica, ativo=True, receber_agenda_diaria=True):
        ags = Agendamento.objects.filter(medico=med, inicio__gte=ini, inicio__lt=ini + timedelta(days=1)).exclude(
            status='cancelado').select_related('paciente', 'tipo').order_by('inicio')
        if not ags:
            continue
        linhas = '\n'.join(f'{timezone.localtime(a.inicio):%H:%M} - {a.paciente.nome} ({a.tipo.nome}) '
                           f'[{a.get_status_display()}]' for a in ags)
        titulo = f'Sua agenda de hoje: {len(ags)} atendimento(s)'
        criado = _lembrete_unico_hoje(clinica, f'agenda_med_{med.pk}', titulo, linhas, usuario=med.usuario,
                                      link=reverse('agenda:dia') + f'?medico={med.pk}')
        if criado:
            n += 1
            email = med.email or (med.usuario.email if med.usuario else '')
            enfileirar(clinica, med.nome, telefone=med.celular, email=email, assunto=titulo,
                       mensagem=f'Olá {med.nome}!\n{titulo}\n\n{linhas}', evento='agenda_medico')
    return n


def lembretes_usuarios(clinica):
    from callcenter.models import ContatoPaciente
    from estoque.models import Produto
    from financeiro.models import Lancamento
    hoje = timezone.localdate()
    n = 0
    cc = ContatoPaciente.objects.filter(clinica=clinica, status__in=('pendente', 'em_andamento', 'sem_resposta'),
                                        data_prevista__lte=hoje).count()
    if cc and _lembrete_unico_hoje(clinica, 'callcenter', f'{cc} contato(s) de call center para hoje',
                                   link=reverse('callcenter:fila')):
        n += 1
    baixo = Produto.objects.filter(clinica=clinica, ativo=True, saldo__lte=F('estoque_minimo')).count()
    if baixo and _lembrete_unico_hoje(clinica, 'estoque', f'{baixo} produto(s) com estoque baixo',
                                      link=reverse('estoque:produto_list') + '?baixo=1'):
        n += 1
    venc = Lancamento.objects.filter(clinica=clinica, status='pendente', vencimento__lte=hoje)
    if venc.exists() and _lembrete_unico_hoje(
            clinica, 'financeiro', f'{venc.count()} lançamento(s) financeiro(s) vencendo/vencidos',
            link=reverse('financeiro:lancamentos') + '?status=atrasado'):
        n += 1
    from estoque.compras import lotes_a_vencer
    vencendo = lotes_a_vencer(clinica, 30)
    if vencendo and _lembrete_unico_hoje(
            clinica, 'lotes', f'{len(vencendo)} lote(s) vencendo em até 30 dias',
            mensagem=', '.join(f'{m.produto.nome} ({m.validade:%d/%m})' for m in vencendo[:6]),
            link=reverse('estoque:lotes') + '?dias=30'):
        n += 1
    # lembretes manuais marcados para envio por e-mail
    Usuario = get_user_model()
    for lem in Lembrete.objects.filter(clinica=clinica, enviar_email=True, email_enviado=False, concluido=False,
                                       data_hora__lte=timezone.now()).select_related('usuario'):
        destinos = [lem.usuario] if lem.usuario else Usuario.objects.filter(
            vinculos__clinica=clinica, vinculos__ativo=True)
        for u in destinos:
            enfileirar(clinica, str(u), email=u.email, telefone=u.telefone, assunto=f'Lembrete: {lem.titulo}',
                       mensagem=f'Lembrete: {lem.titulo}\n{lem.mensagem}', evento='lembrete_usuario')
        lem.email_enviado = True
        lem.save(update_fields=['email_enviado'])
        n += 1
    return n


def aniversariantes(clinica):
    """Felicitações automáticas (1x por ano por paciente), a partir das 8h."""
    from cadastros.models import Paciente

    from .models import Notificacao
    from .services import montar_texto
    if not clinica.enviar_aniversario or timezone.localtime().hour < 8:
        return 0
    hoje = timezone.localdate()
    n = 0
    for p in Paciente.objects.filter(clinica=clinica, ativo=True, aceita_campanhas=True,
                                     data_nascimento__month=hoje.month, data_nascimento__day=hoje.day):
        if Notificacao.objects.filter(clinica=clinica, evento='aniversario', nome_destinatario=p.nome,
                                      criado_em__year=hoje.year).exists():
            continue
        enfileirar(clinica, p.nome, telefone=p.celular if p.aceita_whatsapp else None,
                   email=p.email if p.aceita_email else None, assunto='Feliz aniversário!',
                   mensagem=montar_texto(clinica.msg_aniversario, clinica, p), evento='aniversario')
        n += 1
    return n


def _ouvidoria(clinica):
    from ouvidoria.services import rotina_diaria
    return rotina_diaria(clinica)


def processar_lembretes():
    resumo = {}
    for clinica in Clinica.objects.filter(ativa=True):
        clinica.ativar_fuso()
        try:
            resumo[clinica.nome] = {
                'pacientes': lembretes_pacientes(clinica),
                'medicos': agenda_diaria_medicos(clinica),
                'usuarios': lembretes_usuarios(clinica),
                'aniversarios': aniversariantes(clinica),
                'ouvidoria': _ouvidoria(clinica),
            }
        except Exception:  # noqa: BLE001
            log.exception('Erro ao processar lembretes da clínica %s', clinica.pk)
    timezone.deactivate()
    try:
        from assinaturas.tarefas import processar as processar_saas
        resumo['saas'] = processar_saas()
    except Exception:  # noqa: BLE001
        log.exception('Erro nas rotinas do SaaS')
    return resumo
