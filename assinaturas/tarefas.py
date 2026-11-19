"""Rotinas do SaaS: gerar faturas mensais, marcar inadimplência e avisar por e-mail."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import Assinatura, Fatura


def gerar_faturas(forcar=False):
    """Gera a fatura do mês para assinaturas ativas/inadimplentes (e para testes que acabam neste mês)."""
    hoje = timezone.localdate()
    n = 0
    for a in Assinatura.objects.select_related('plano', 'clinica').exclude(status__in=('cancelada',)):
        if not a.plano.preco_mensal:
            continue
        venc = a.vencimento_em(hoje.year, hoje.month)
        if a.status == 'teste':
            if not a.teste_ate:
                continue
            venc = max(venc, a.teste_ate)
            if (a.teste_ate - hoje).days > 7 and not forcar:
                continue
        elif (venc - hoje).days > 7 and not forcar:
            continue
        comp = venc.strftime('%Y-%m')
        f, criada = Fatura.objects.get_or_create(assinatura=a, competencia=comp,
                                                 defaults={'valor': a.plano.preco_mensal, 'vencimento': venc})
        if criada:
            n += 1
            _avisar(a, f)
    return n


def _avisar(a, f):
    destino = a.responsavel_email or a.clinica.email
    if not destino:
        return
    from django.core.mail import send_mail
    from .views import pix_da_fatura
    pix = pix_da_fatura(f)
    send_mail(f'{settings.SAAS_NOME}: fatura {f.competencia}',
              f'Olá! A fatura de {f.competencia} da {a.clinica} ({a.plano.nome}) no valor de R$ {f.valor} vence em '
              f'{f.vencimento:%d/%m/%Y}.' + (f'\n\nPIX copia e cola:\n{pix}' if pix else '') +
              '\n\nA segunda via fica em Administrativo > Minha assinatura.',
              settings.DEFAULT_FROM_EMAIL, [destino], fail_silently=True)


def atualizar_status():
    hoje = timezone.localdate()
    n = 0
    for a in Assinatura.objects.filter(status__in=('ativa', 'teste')):
        if a.faturas.filter(status='pendente', vencimento__lt=hoje - timedelta(days=1)).exists():
            a.status = 'inadimplente'
            a.save(update_fields=['status'])
            n += 1
    return n


def processar():
    if not getattr(settings, 'SAAS_ATIVO', False):
        return {}
    return {'faturas': gerar_faturas(), 'inadimplentes': atualizar_status()}
