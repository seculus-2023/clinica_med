from django.urls import reverse
from django.utils import timezone

from .models import InsumoAtendimento, MovimentoEstoque


def baixar_insumos(ag):
    """Desconta do estoque os insumos do tipo de atendimento quando ele é concluído (rastreio por paciente)."""
    if MovimentoEstoque.objects.filter(agendamento=ag).exists():
        return 0
    from contas.models import Lembrete
    n = 0
    for ins in InsumoAtendimento.objects.filter(tipo=ag.tipo, clinica=ag.clinica).select_related('produto'):
        prod = ins.produto
        lote = prod.movimentos.filter(tipo='entrada', validade__gte=timezone.localdate()).order_by('validade').first()
        MovimentoEstoque.objects.create(
            clinica=ag.clinica, produto=prod, tipo='saida', quantidade=ins.quantidade, paciente=ag.paciente,
            agendamento=ag, lote=lote.lote if lote else '', validade=lote.validade if lote else None,
            motivo=f'Baixa automática - {ag.tipo} ({timezone.localtime(ag.inicio):%d/%m/%Y %H:%M})')
        prod.refresh_from_db()
        if prod.abaixo_minimo:
            Lembrete.objects.create(clinica=ag.clinica, origem='estoque_min', titulo=f'Estoque mínimo: {prod.nome}',
                                    mensagem=f'Saldo atual {prod.saldo} {prod.unidade} (mínimo {prod.estoque_minimo}).',
                                    link=reverse('estoque:produto_kardex', args=[prod.pk]))
        n += 1
    return n


def estornar_insumos(ag):
    for m in MovimentoEstoque.objects.filter(agendamento=ag):
        m.delete()
