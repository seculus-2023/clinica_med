from django.db.models import Max
from django.urls import reverse

from .models import GuiaTISS, LoteTISS, PrecoConvenio


def requer_autorizacao(operadora, plano, tipo):
    if not operadora:
        return False
    preco = PrecoConvenio.buscar(operadora, plano, tipo)
    return operadora.exige_autorizacao or bool(preco and preco.requer_autorizacao)


def criar_guia(ag):
    """Gera a guia TISS quando um atendimento por convênio é concluído."""
    if not ag.operadora_id or GuiaTISS.objects.filter(agendamento=ag).exists():
        return None
    preco = PrecoConvenio.buscar(ag.operadora, ag.plano, ag.tipo)
    from .models import codigo_tuss_do_tipo
    codigo = preco.codigo if preco else codigo_tuss_do_tipo(ag.tipo)
    eh_consulta = codigo.startswith('1010') if codigo else any(
        p in ag.tipo.nome.lower() for p in ('consulta', 'retorno', 'teleconsulta'))
    tipo = 'consulta' if eh_consulta else 'sp_sadt'
    if not codigo:
        codigo = '10101012' if eh_consulta else ''
    from prontuario.models import Atendimento
    at = Atendimento.objects.filter(agendamento=ag).select_related('cid_principal').first()
    anteriores = ag.paciente.agendamentos.filter(medico=ag.medico, status='concluido').exclude(pk=ag.pk).exists()
    g = GuiaTISS.objects.create(
        clinica=ag.clinica, tipo=tipo, agendamento=ag, paciente=ag.paciente, medico=ag.medico,
        operadora=ag.operadora, plano=ag.plano, numero_guia=GuiaTISS.proximo_numero(ag.clinica),
        senha=ag.autorizacao_senha, carteirinha=ag.paciente.carteirinha or '',
        data_atendimento=ag.inicio.date(), tipo_consulta='2' if anteriores else '1',
        cid=at.cid_principal.codigo if at and at.cid_principal else '',
        indicacao_clinica=(at.hipotese_diagnostica[:500] if at else ''),
        codigo_procedimento=codigo, descricao_procedimento=ag.tipo.nome[:150],
        valor_unitario=ag.valor or (preco.valor if preco else 0))
    if not g.carteirinha:
        from contas.models import Lembrete
        Lembrete.objects.create(clinica=ag.clinica, origem='tiss', titulo=f'Guia {g.numero_guia}: paciente sem carteirinha',
                                mensagem=str(ag.paciente), link=reverse('convenios:guia_editar', args=[g.pk]))
    return g


def proximo_lote(clinica):
    return (LoteTISS.objects.filter(clinica=clinica).aggregate(m=Max('numero'))['m'] or 0) + 1
