"""Regras da fila de senhas. Toda mudança concorrente é feita com bloqueio de linha no banco."""
from datetime import timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from agenda.models import Agendamento
from agenda.services import mudar_status
from contas.models import Vinculo

from .models import ChamadaSenha, ConfigPainel, PontoAtendimento, Senha, ServicoSenha

IDADE_PREFERENCIAL = 60
STATUS_ATIVOS = ('chamada', 'em_atendimento')
# Depois de uma queda de conexão, a TV não fala chamadas mais antigas que isto
JANELA_FALA_SEGUNDOS = 60
TRANSICOES = {
    'iniciar': (('chamada',), 'em_atendimento'),
    'concluir': (('chamada', 'em_atendimento'), 'concluida'),
    'ausente': (('chamada',), 'ausente'),
    'cancelar': (('aguardando', 'chamada'), 'cancelada'),
    'devolver': (('chamada', 'ausente'), 'aguardando'),
}


class ErroSenha(Exception):
    """Operação não permitida; a mensagem é exibida ao usuário."""


def _fuso(clinica):
    try:
        return ZoneInfo(clinica.fuso_horario or settings.TIME_ZONE)
    except Exception:  # noqa: BLE001 - fuso inválido: usa o padrão do sistema
        return ZoneInfo(settings.TIME_ZONE)


def hoje(clinica):
    return timezone.localdate(timezone=_fuso(clinica))


def garantir_padroes(clinica):
    """Na primeira utilização, cria filas e guichês iniciais (editáveis) e o painel."""
    config, _ = ConfigPainel.objects.get_or_create(clinica=clinica)
    if not ServicoSenha.objects.filter(clinica=clinica).exists():
        for ordem, (prefixo, nome) in enumerate([('A', 'Recepção'), ('C', 'Convênios'), ('E', 'Exames')], 1):
            ServicoSenha.objects.get_or_create(clinica=clinica, prefixo=prefixo,
                                               defaults={'nome': nome, 'ordem': ordem})
    if not PontoAtendimento.objects.filter(clinica=clinica).exists():
        for nome in ('Guichê 1', 'Guichê 2'):
            PontoAtendimento.objects.get_or_create(clinica=clinica, nome=nome)
    return config


@transaction.atomic
def emitir(clinica, servico, preferencial=False, paciente=None, agendamento=None, usuario=None):
    servico = ServicoSenha.objects.select_for_update().get(pk=servico.pk, clinica=clinica)
    data = hoje(clinica)
    ultimo = Senha.objects.filter(clinica=clinica, data=data, servico=servico,
                                  preferencial=preferencial).aggregate(m=Max('numero'))['m'] or 0
    numero = ultimo + 1
    codigo = f"{servico.prefixo}{'P' if preferencial else ''}{numero:03d}"
    return Senha.objects.create(clinica=clinica, servico=servico, data=data, numero=numero, codigo=codigo,
                                preferencial=preferencial, paciente=paciente, agendamento=agendamento,
                                emitida_por=usuario)


def _eh_preferencial(paciente):
    idade = paciente.idade
    return idade is not None and idade >= IDADE_PREFERENCIAL


@transaction.atomic
def emitir_para_agendamento(ag, usuario=None):
    """Gera a senha do atendimento (uma só por agendamento) e registra a chegada do paciente."""
    Agendamento.objects.select_for_update().filter(pk=ag.pk).first()
    existente = Senha.objects.filter(agendamento=ag).first()
    if existente:
        return existente, False
    if timezone.localtime(ag.inicio, ZoneInfo(ag.clinica.fuso_horario or settings.TIME_ZONE)).date() != hoje(ag.clinica):
        raise ErroSenha('A senha só pode ser gerada no dia do atendimento.')
    if ag.status not in ('agendado', 'confirmado', 'aguardando'):
        raise ErroSenha(f'Atendimento com situação "{ag.get_status_display()}" não recebe senha.')
    garantir_padroes(ag.clinica)
    servico = ServicoSenha.objects.filter(clinica=ag.clinica, ativo=True).first()
    if servico is None:
        raise ErroSenha('Cadastre ao menos um serviço de senha ativo.')
    senha = emitir(ag.clinica, servico, _eh_preferencial(ag.paciente), ag.paciente, ag, usuario)
    if ag.status != 'aguardando':
        mudar_status(ag, 'aguardando')
    return senha, True


def e_gestor(clinica, usuario):
    """Administrador da clínica: assume qualquer guichê e libera guichês presos."""
    if usuario.is_superuser:
        return True
    vinculo = Vinculo.objects.select_related('perfil').filter(usuario=usuario, clinica=clinica, ativo=True).first()
    return bool(vinculo and vinculo.perfil.nivel('administrativo') == 'editar')


def pode_operar(ponto, usuario):
    return e_gestor(ponto.clinica, usuario) or ponto.responsaveis.filter(pk=usuario.pk).exists()


def operador_atual(ponto, data=None):
    """Quem está no guichê hoje. A abertura vale só para o dia: no dia seguinte o guichê volta a ficar livre."""
    if not ponto.operador_id or not ponto.operador_desde:
        return None
    data = data or hoje(ponto.clinica)
    return ponto.operador if timezone.localtime(ponto.operador_desde, _fuso(ponto.clinica)).date() == data else None


def guiche_do_usuario(clinica, usuario):
    ponto = PontoAtendimento.objects.select_related('clinica', 'operador').filter(
        clinica=clinica, operador=usuario, ativo=True).first()
    return ponto if ponto and operador_atual(ponto) else None


def situacao_guiches(clinica, usuario):
    data = hoje(clinica)
    gestor = e_gestor(clinica, usuario)
    autorizados = set(usuario.guiches_autorizados.filter(clinica=clinica).values_list('pk', flat=True))
    saida = []
    for ponto in PontoAtendimento.objects.filter(clinica=clinica, ativo=True).select_related('clinica', 'operador'):
        operador = operador_atual(ponto, data)
        saida.append({'ponto': ponto, 'operador': operador, 'meu': bool(operador and operador.pk == usuario.pk),
                      'pode_assumir': operador is None and (gestor or ponto.pk in autorizados),
                      'pode_liberar': gestor and operador is not None and operador.pk != usuario.pk})
    return saida


def _tem_senha_ativa(ponto, data):
    return Senha.objects.filter(clinica=ponto.clinica, data=data, ponto=ponto, status__in=STATUS_ATIVOS).first()


@transaction.atomic
def assumir_guiche(clinica, ponto, usuario):
    ponto = PontoAtendimento.objects.select_for_update().get(pk=ponto.pk, clinica=clinica)
    if not ponto.ativo:
        raise ErroSenha(f'{ponto.nome} está inativo.')
    if not pode_operar(ponto, usuario):
        raise ErroSenha(f'Você não está autorizado a atender em {ponto.nome}.')
    data = hoje(clinica)
    atual = operador_atual(ponto, data)
    if atual and atual.pk == usuario.pk:
        return ponto
    if atual:
        raise ErroSenha(f'{ponto.nome} está em uso por {atual}.')
    anterior = PontoAtendimento.objects.select_for_update().filter(clinica=clinica, operador=usuario).first()
    if anterior:
        ativa = _tem_senha_ativa(anterior, data)
        if ativa:
            raise ErroSenha(f'Finalize a senha {ativa.codigo} em {anterior.nome} antes de trocar de guichê.')
        anterior.operador, anterior.operador_desde = None, None
        anterior.save(update_fields=['operador', 'operador_desde', 'atualizado_em'])
    ponto.operador, ponto.operador_desde = usuario, timezone.now()
    ponto.save(update_fields=['operador', 'operador_desde', 'atualizado_em'])
    return ponto


@transaction.atomic
def sair_guiche(clinica, usuario):
    ponto = PontoAtendimento.objects.select_for_update().filter(clinica=clinica, operador=usuario).first()
    if ponto is None:
        raise ErroSenha('Você não está em nenhum guichê.')
    ativa = _tem_senha_ativa(ponto, hoje(clinica))
    if ativa:
        raise ErroSenha(f'Finalize a senha {ativa.codigo} antes de sair de {ponto.nome}.')
    ponto.operador, ponto.operador_desde = None, None
    ponto.save(update_fields=['operador', 'operador_desde', 'atualizado_em'])
    return ponto


@transaction.atomic
def liberar_guiche(clinica, ponto, usuario):
    """O gestor libera um guichê preso. Uma senha em andamento fica para quem assumir o guichê."""
    if not e_gestor(clinica, usuario):
        raise ErroSenha('Somente o administrador pode liberar um guichê.')
    ponto = PontoAtendimento.objects.select_for_update().get(pk=ponto.pk, clinica=clinica)
    ponto.operador, ponto.operador_desde = None, None
    ponto.save(update_fields=['operador', 'operador_desde', 'atualizado_em'])
    return ponto


def _exigir_operador(senha, usuario):
    """Senha em andamento em um guichê só é movida por quem está nele ou pelo administrador."""
    if not senha.ponto_id or senha.status not in STATUS_ATIVOS or e_gestor(senha.clinica, usuario):
        return
    atual = operador_atual(senha.ponto)
    if not atual or atual.pk != usuario.pk:
        raise ErroSenha(f'A senha {senha.codigo} está em {senha.ponto.nome}, com outro atendente.')


def _registrar_chamada(senha, local, ponto=None, usuario=None):
    senha.status = 'chamada'
    senha.local = local
    senha.ponto = ponto
    senha.chamada_em = timezone.now()
    senha.chamada_por = usuario
    senha.vezes_chamada += 1
    senha.save(update_fields=['status', 'local', 'ponto', 'chamada_em', 'chamada_por', 'vezes_chamada',
                              'atualizado_em'])
    ChamadaSenha.objects.create(clinica=senha.clinica, senha=senha, local=local, texto=senha.texto_fala,
                                ponto=ponto, usuario=usuario)
    return senha


@transaction.atomic
def chamar_proxima(clinica, ponto, usuario, senha_id=None):
    """Chama a próxima senha (preferenciais primeiro) ou uma senha específica da fila."""
    ponto = PontoAtendimento.objects.select_for_update().get(pk=ponto.pk, clinica=clinica)
    data = hoje(clinica)
    atual = operador_atual(ponto, data)
    if not atual or atual.pk != usuario.pk:
        raise ErroSenha(f'Assuma {ponto.nome} antes de chamar senhas.')
    ocupada = Senha.objects.filter(clinica=clinica, data=data, ponto=ponto, status__in=STATUS_ATIVOS).first()
    if ocupada:
        raise ErroSenha(f'Finalize a senha {ocupada.codigo} antes de chamar outra em {ponto.nome}.')
    fila = Senha.objects.filter(clinica=clinica, data=data, status='aguardando')
    if senha_id:
        fila = fila.filter(pk=senha_id)
    senha = fila.order_by('-preferencial', 'criado_em', 'id').select_for_update(skip_locked=True).first()
    if senha is None:
        raise ErroSenha('Esta senha já foi chamada.' if senha_id else 'Não há senhas aguardando.')
    return _registrar_chamada(senha, ponto.nome, ponto, usuario)


@transaction.atomic
def rechamar(senha, usuario):
    senha = Senha.objects.select_for_update().select_related('clinica').get(pk=senha.pk)
    if senha.status != 'chamada':
        raise ErroSenha('Só é possível repetir uma senha que está em chamada.')
    _exigir_operador(senha, usuario)
    return _registrar_chamada(senha, senha.local, senha.ponto, usuario)


@transaction.atomic
def aplicar_acao(senha, acao, usuario):
    if acao not in TRANSICOES:
        raise ErroSenha('Ação inválida.')
    senha = Senha.objects.select_for_update().get(pk=senha.pk)
    origens, destino = TRANSICOES[acao]
    if senha.status not in origens:
        raise ErroSenha(f'A senha {senha.codigo} está "{senha.get_status_display()}" e não permite esta ação.')
    _exigir_operador(senha, usuario)
    agora = timezone.now()
    senha.status = destino
    if destino == 'em_atendimento':
        senha.inicio_em = senha.inicio_em or agora
        senha.iniciada_por = usuario
    elif destino in ('concluida', 'ausente', 'cancelada'):
        senha.fim_em = agora
        if destino == 'concluida':
            senha.concluida_por = usuario
            inicio = senha.inicio_em or senha.chamada_em
            senha.tempo_guiche = agora - inicio if senha.ponto_id and inicio else None
    else:  # devolvida à fila: a próxima chamada recomeça o histórico
        senha.ponto, senha.local, senha.fim_em, senha.inicio_em = None, '', None, None
        senha.chamada_por, senha.iniciada_por = None, None
    senha.save()
    return senha


@transaction.atomic
def chamar_agendamento(ag, usuario=None):
    """O profissional chama o paciente para a sala (ou para o seu atendimento)."""
    if ag.status != 'aguardando':
        raise ErroSenha('Só é possível chamar pacientes que já chegaram.')
    senha, _ = emitir_para_agendamento(ag, usuario)
    senha = Senha.objects.select_for_update().select_related('clinica').get(pk=senha.pk)
    if senha.data != hoje(ag.clinica):
        raise ErroSenha('A senha deste atendimento não é de hoje.')
    local = ag.recurso.nome if ag.recurso_id else ag.medico.nome
    return _registrar_chamada(senha, local, usuario=usuario)


def _item(chamada):
    s = chamada.senha
    return {'codigo': s.codigo, 'local': chamada.local, 'servico': s.servico.nome, 'preferencial': s.preferencial}


def dados_painel(config, desde=None):
    """Dados públicos da TV. Nunca incluir nome ou qualquer dado do paciente."""
    clinica = config.clinica
    data = hoje(clinica)
    recentes = list(ChamadaSenha.objects.filter(clinica=clinica, senha__data=data)
                    .select_related('senha__servico').order_by('-id')[:30])
    vistas, chamadas = set(), []
    for c in recentes:
        if c.senha_id not in vistas:
            vistas.add(c.senha_id)
            chamadas.append(c)
    ultimo_id = recentes[0].id if recentes else (
        ChamadaSenha.objects.filter(clinica=clinica).order_by('-id').values_list('id', flat=True).first() or 0)
    novas = []
    if desde is not None:
        limite = timezone.now() - timedelta(seconds=JANELA_FALA_SEGUNDOS)
        qs = (ChamadaSenha.objects.filter(clinica=clinica, id__gt=desde, criado_em__gte=limite, senha__data=data)
              .select_related('senha__servico').order_by('id')[:10])
        novas = [{'id': c.id, 'texto': c.texto, **_item(c)} for c in qs]
    # Hora de parede da clínica: o relógio da TV não depende do fuso configurado no aparelho
    local = timezone.localtime(timezone.now(), ZoneInfo(clinica.fuso_horario or settings.TIME_ZONE))
    return {
        'relogio_ms': int(local.replace(tzinfo=dt_timezone.utc).timestamp() * 1000),
        'titulo': config.titulo or clinica.nome,
        'mensagem': config.mensagem,
        'voz': config.voz_ativa,
        'repeticoes': config.repeticoes,
        'ultimo_id': ultimo_id,
        'atual': _item(chamadas[0]) if chamadas else None,
        'anteriores': [_item(c) for c in chamadas[1:6]],
        'aguardando': Senha.objects.filter(clinica=clinica, data=data, status='aguardando').count(),
        'novas': novas,
    }
