"""Regras da ouvidoria: protocolo, prazos, tramitação e avisos ao manifestante e à equipe."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from contas.models import Lembrete, Usuario

from .models import STATUS_ABERTOS, Andamento, ConfigOuvidoria, Manifestacao, Setor

SETORES_PADRAO = ['Recepção', 'Atendimento médico', 'Enfermagem', 'Exames', 'Financeiro', 'Convênios',
                  'Agendamento / call center', 'Estrutura e limpeza']
ALFABETO_CHAVE = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'   # sem 0/O e 1/I/L, que se confundem ao digitar


class ErroOuvidoria(Exception):
    pass


def garantir_config(clinica):
    config, criada = ConfigOuvidoria.objects.get_or_create(clinica=clinica)
    if criada and not Setor.objects.filter(clinica=clinica).exists():
        Setor.objects.bulk_create([Setor(clinica=clinica, nome=n) for n in SETORES_PADRAO])
    return config


def hash_chave(chave):
    return hashlib.sha256(chave.strip().upper().replace('-', '').encode()).hexdigest()


def nova_chave():
    bruta = ''.join(secrets.choice(ALFABETO_CHAVE) for _ in range(8))
    return f'{bruta[:4]}-{bruta[4:]}'


def link_publico(m):
    return settings.SITE_URL.rstrip('/') + m.caminho_publico


def _proximo_protocolo(clinica):
    config = ConfigOuvidoria.objects.select_for_update().get(clinica=clinica)
    ano = timezone.localdate().year
    if config.ano != ano:
        config.ano, config.ultimo_numero = ano, 0
    config.ultimo_numero += 1
    config.save(update_fields=['ano', 'ultimo_numero'])
    return f'{ano}-{config.ultimo_numero:05d}'


def registrar(clinica, *, tipo, assunto, descricao, canal, usuario=None, paciente=None, notificar=True, **dados):
    """Cria a manifestação com protocolo e chave de acesso. Retorna (manifestação, chave em texto)."""
    config = garantir_config(clinica)
    if dados.get('anonima'):
        dados.update(nome='', email='', telefone='', aceita_contato=False, sigilosa=False)
        paciente = None
    elif paciente is not None:
        dados['nome'] = dados.get('nome') or paciente.nome
        dados['email'] = dados.get('email') or paciente.email
        dados['telefone'] = dados.get('telefone') or paciente.celular
        dados.setdefault('relacao', 'paciente')
    if tipo == 'denuncia':
        dados['prioridade'] = 1
    setor = dados.get('setor')
    if setor and setor.responsavel_id and not dados.get('responsavel'):
        dados['responsavel'] = setor.responsavel
    chave = nova_chave()
    with transaction.atomic():
        m = Manifestacao.objects.create(
            clinica=clinica, protocolo=_proximo_protocolo(clinica), chave_hash=hash_chave(chave), tipo=tipo,
            assunto=assunto[:150], descricao=descricao, canal=canal, paciente=paciente, registrada_por=usuario,
            prazo=timezone.localdate() + timedelta(days=config.prazo_dias), **dados)
        Andamento.objects.create(manifestacao=m, tipo='registro', publico=True, usuario=usuario,
                                 texto=f'Manifestação registrada ({m.get_canal_display()}).')
    _alertar_equipe(config, m)
    if notificar:
        _avisar_manifestante(m, 'Manifestação registrada',
                             f'{clinica.nome}: recebemos sua manifestação ({m.get_tipo_display().lower()}). '
                             f'Protocolo {m.protocolo}, chave de acesso {chave}. Resposta até '
                             f'{m.prazo:%d/%m/%Y}. Acompanhe: {link_publico(m)}')
    return m, chave


def equipe(clinica):
    """Usuários que editam a ouvidoria (recebem os alertas quando não há ouvidor definido)."""
    return [v.usuario for v in clinica.vinculos.filter(ativo=True, usuario__is_active=True)
            .select_related('usuario', 'perfil') if v.perfil.nivel('ouvidoria') == 'editar']


def _alertar_equipe(config, m):
    clinica = m.clinica
    titulo = f'Ouvidoria: nova {m.get_tipo_display().lower()} - protocolo {m.protocolo}'[:150]
    texto = m.assunto if not m.sigilosa else 'Manifestação com identidade sob sigilo.'
    link = reverse('ouvidoria:detalhe', args=[m.pk])
    destinos = [config.ouvidor] if config.ouvidor_id else equipe(clinica)
    if m.responsavel_id and m.responsavel not in destinos:
        destinos.append(m.responsavel)
    for u in destinos:
        Lembrete.objects.create(clinica=clinica, usuario=u, origem='ouvidoria', titulo=titulo, mensagem=texto,
                                link=link)
    if config.email_alerta:
        from notificacoes.services import enfileirar
        enfileirar(clinica, 'Ouvidoria', email=config.email_alerta, whatsapp=False, sms=False, assunto=titulo,
                   mensagem=f'{titulo}\nAssunto: {texto}\nPrazo: {m.prazo:%d/%m/%Y}\n'
                            f'{settings.SITE_URL.rstrip("/")}{link}', evento='ouvidoria_alerta')


def _avisar_manifestante(m, assunto, mensagem):
    if m.anonima or not m.aceita_contato or not (m.telefone or m.email):
        return []
    from notificacoes.services import enfileirar
    return enfileirar(m.clinica, m.nome or 'Manifestante', telefone=m.telefone, email=m.email,
                      assunto=f'{assunto} - protocolo {m.protocolo}', mensagem=mensagem, evento='ouvidoria')


def _andamento(m, tipo, usuario=None, texto='', **kw):
    return Andamento.objects.create(manifestacao=m, tipo=tipo, usuario=usuario, texto=texto,
                                    publico=tipo in Andamento.PUBLICOS, **kw)


def _salvar(m, *campos):
    m.save(update_fields=[*campos, 'atualizado_em'])


def nota(m, usuario, texto):
    _andamento(m, 'nota', usuario, texto)
    if m.status == 'nova':
        m.status = 'em_analise'
        _salvar(m, 'status')


def encaminhar(m, usuario, destino, setor, texto):
    if m.encerrada:
        raise ErroOuvidoria('Reabra a manifestação antes de encaminhar.')
    destino = destino or (setor.responsavel if setor else None)
    if destino is None:
        raise ErroOuvidoria('Escolha o usuário que vai analisar (ou um setor com responsável).')
    _andamento(m, 'encaminhamento', usuario, texto, destino=destino, setor=setor)
    m.status, m.responsavel = 'encaminhada', destino
    if setor:
        m.setor = setor
    _salvar(m, 'status', 'responsavel', 'setor')
    Lembrete.objects.create(
        clinica=m.clinica, usuario=destino, origem='ouvidoria',
        titulo=f'Ouvidoria: protocolo {m.protocolo} encaminhado para você'[:150],
        mensagem=f'{texto}\nPrazo: {m.prazo:%d/%m/%Y}'.strip(), link=reverse('ouvidoria:detalhe', args=[m.pk]))


def parecer(m, usuario, texto):
    if m.encerrada:
        raise ErroOuvidoria('Manifestação já encerrada.')
    _andamento(m, 'parecer', usuario, texto)
    m.status = 'em_analise'
    _salvar(m, 'status')
    config = garantir_config(m.clinica)
    destinos = [config.ouvidor] if config.ouvidor_id else equipe(m.clinica)
    for u in destinos:
        if u != usuario:
            Lembrete.objects.create(clinica=m.clinica, usuario=u, origem='ouvidoria',
                                    titulo=f'Ouvidoria: parecer recebido no protocolo {m.protocolo}'[:150],
                                    mensagem=f'{usuario}: {texto}'[:500],
                                    link=reverse('ouvidoria:detalhe', args=[m.pk]))


def responder(m, usuario, texto, concluir=False, conclusao=''):
    if m.encerrada:
        raise ErroOuvidoria('Reabra a manifestação antes de responder.')
    agora = timezone.now()
    _andamento(m, 'resposta', usuario, texto)
    m.primeira_resposta_em = m.primeira_resposta_em or agora
    m.respondida_em = agora
    m.status = 'respondida'
    campos = ['status', 'primeira_resposta_em', 'respondida_em']
    if concluir:
        m.status, m.encerrada_em, m.conclusao = 'concluida', agora, conclusao or m.conclusao
        campos += ['encerrada_em', 'conclusao']
    _salvar(m, *campos)
    _avisar_manifestante(m, 'Resposta da ouvidoria',
                         f'{m.clinica.nome}: sua manifestação protocolo {m.protocolo} foi respondida. '
                         f'Veja a resposta e avalie o atendimento: {link_publico(m)}')


def prorrogar(m, usuario, dias, motivo):
    config = garantir_config(m.clinica)
    if not m.aberta:
        raise ErroOuvidoria('Só é possível prorrogar manifestações em aberto.')
    if m.prorrogada:
        raise ErroOuvidoria('O prazo desta manifestação já foi prorrogado uma vez.')
    if not 1 <= dias <= config.prorrogacao_dias:
        raise ErroOuvidoria(f'A prorrogação deve ser de 1 a {config.prorrogacao_dias} dias.')
    m.prazo += timedelta(days=dias)
    m.prorrogada = True
    _salvar(m, 'prazo', 'prorrogada')
    _andamento(m, 'prorrogacao', usuario, f'Prazo prorrogado para {m.prazo:%d/%m/%Y}. Motivo: {motivo}')
    _avisar_manifestante(m, 'Prazo prorrogado',
                         f'{m.clinica.nome}: o prazo de resposta do protocolo {m.protocolo} foi prorrogado para '
                         f'{m.prazo:%d/%m/%Y}. Motivo: {motivo}')


def concluir(m, usuario, conclusao, texto=''):
    if m.encerrada:
        raise ErroOuvidoria('Manifestação já encerrada.')
    m.status, m.conclusao, m.encerrada_em = 'concluida', conclusao, timezone.now()
    _salvar(m, 'status', 'conclusao', 'encerrada_em')
    _andamento(m, 'conclusao', usuario, texto or f'Manifestação concluída: {m.get_conclusao_display()}.')


def arquivar(m, usuario, motivo):
    if m.encerrada:
        raise ErroOuvidoria('Manifestação já encerrada.')
    m.status, m.encerrada_em = 'arquivada', timezone.now()
    _salvar(m, 'status', 'encerrada_em')
    _andamento(m, 'arquivamento', usuario, f'Arquivada. Motivo: {motivo}')


def reabrir(m, usuario, motivo, pelo_manifestante=False):
    if m.aberta:
        raise ErroOuvidoria('A manifestação já está em aberto.')
    config = garantir_config(m.clinica)
    m.status, m.encerrada_em, m.conclusao = 'em_analise', None, ''
    novo_prazo = timezone.localdate() + timedelta(days=config.prazo_dias)
    m.prazo = max(m.prazo, novo_prazo)
    _salvar(m, 'status', 'encerrada_em', 'conclusao', 'prazo')
    if not pelo_manifestante:
        _andamento(m, 'reabertura', usuario, f'Reaberta. Motivo: {motivo}')


def mensagem_manifestante(m, texto):
    """Complemento ou réplica enviada pelo manifestante na página de acompanhamento."""
    if m.status == 'arquivada':
        raise ErroOuvidoria('Esta manifestação foi arquivada. Registre uma nova, se necessário.')
    _andamento(m, 'manifestante', texto=texto)
    if m.status in ('respondida', 'concluida'):
        reabrir(m, None, '', pelo_manifestante=True)
    config = garantir_config(m.clinica)
    destinos = [m.responsavel] if m.responsavel_id else (
        [config.ouvidor] if config.ouvidor_id else equipe(m.clinica))
    for u in destinos:
        Lembrete.objects.create(clinica=m.clinica, usuario=u, origem='ouvidoria',
                                titulo=f'Ouvidoria: nova mensagem no protocolo {m.protocolo}'[:150],
                                mensagem=texto[:500], link=reverse('ouvidoria:detalhe', args=[m.pk]))


def avaliar(m, resolvida, nota_, comentario=''):
    if m.status not in ('respondida', 'concluida') or m.avaliada_em:
        raise ErroOuvidoria('Avaliação indisponível para esta manifestação.')
    m.avaliacao_resolvida, m.avaliacao_nota, m.avaliacao_comentario = resolvida, nota_, comentario
    m.avaliada_em = timezone.now()
    campos = ['avaliacao_resolvida', 'avaliacao_nota', 'avaliacao_comentario', 'avaliada_em']
    if m.status == 'respondida':
        m.status, m.encerrada_em = 'concluida', m.avaliada_em
        campos += ['status', 'encerrada_em']
    _salvar(m, *campos)
    _andamento(m, 'avaliacao', texto=f'{"Resolvida" if resolvida else "Não resolvida"} · satisfação {nota_}/5'
                                     + (f' · {comentario}' if comentario else ''))
    if not resolvida or nota_ <= 2:
        config = garantir_config(m.clinica)
        for u in ([config.ouvidor] if config.ouvidor_id else equipe(m.clinica)):
            Lembrete.objects.create(clinica=m.clinica, usuario=u, origem='ouvidoria',
                                    titulo=f'Ouvidoria: avaliação negativa no protocolo {m.protocolo}'[:150],
                                    mensagem=comentario[:500], link=reverse('ouvidoria:detalhe', args=[m.pk]))


def abrir_por_nps(avaliacao):
    """Nota baixa com comentário na pesquisa de satisfação vira reclamação na ouvidoria."""
    ag = avaliacao.agendamento
    config = garantir_config(ag.clinica)
    if not config.abrir_por_nps or avaliacao.classificacao != 'detrator' or not avaliacao.comentario.strip():
        return None
    m, _ = registrar(ag.clinica, tipo='reclamacao', canal='nps', paciente=ag.paciente, medico=ag.medico,
                     assunto=f'Pesquisa de satisfação: nota {avaliacao.nota} ({ag.tipo})',
                     descricao=avaliacao.comentario, data_ocorrido=timezone.localtime(ag.inicio).date(),
                     agendamento=ag, notificar=False)
    return m


def visiveis(request):
    """Manifestações que o usuário pode abrir: todas (com acesso ao módulo) ou as encaminhadas a ele."""
    from contas.permissoes import tem_permissao
    qs = Manifestacao.objects.filter(clinica=request.clinica)
    if tem_permissao(request, 'ouvidoria'):
        return qs
    return qs.filter(Q(responsavel=request.user) | Q(andamentos__destino=request.user)).distinct()


def rotina_diaria(clinica):
    """Alertas de prazo e conclusão automática das respondidas sem retorno (roda com os lembretes)."""
    from notificacoes.tarefas import _lembrete_unico_hoje
    config = garantir_config(clinica)
    hoje = timezone.localdate()
    n = 0
    abertas = Manifestacao.objects.filter(clinica=clinica, status__in=STATUS_ABERTOS)
    vencidas = abertas.filter(prazo__lt=hoje).count()
    vencendo = abertas.filter(prazo__gte=hoje, prazo__lte=hoje + timedelta(days=1)).count()
    if vencidas or vencendo:
        partes = [f'{vencidas} com prazo vencido' if vencidas else '', f'{vencendo} vencendo até amanhã'
                  if vencendo else '']
        titulo = 'Ouvidoria: ' + ' e '.join(p for p in partes if p)
        for u in ([config.ouvidor] if config.ouvidor_id else equipe(clinica)):
            if _lembrete_unico_hoje(clinica, 'ouvidoria_prazo', titulo, usuario=u,
                                    link=reverse('ouvidoria:painel') + '?aba=vencidas'):
                n += 1
    if config.concluir_sem_retorno_dias:
        limite = timezone.now() - timedelta(days=config.concluir_sem_retorno_dias)
        for m in Manifestacao.objects.filter(clinica=clinica, status='respondida', respondida_em__lt=limite):
            m.status, m.encerrada_em = 'concluida', timezone.now()
            m.conclusao = m.conclusao or 'atendida'
            _salvar(m, 'status', 'encerrada_em', 'conclusao')
            _andamento(m, 'conclusao', texto='Concluída automaticamente: sem retorno do manifestante após a resposta.')
            n += 1
    return n


def usuarios_da_clinica(clinica):
    return Usuario.objects.filter(vinculos__clinica=clinica, vinculos__ativo=True, is_active=True).distinct() \
        .order_by('first_name', 'username')
