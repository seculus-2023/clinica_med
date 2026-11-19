"""Verificação de interações medicamentosas e alergias numa prescrição."""
import re
import unicodedata

from .models import InteracaoMedicamentosa


def norm(txt):
    return unicodedata.normalize('NFKD', str(txt or '')).encode('ascii', 'ignore').decode().lower()


def _casa(termos, texto):
    return next((t for t in termos if re.search(r'\b' + re.escape(t) + r'\b', texto)), None)


def itens_em_uso(paciente):
    """Medicamentos de uso contínuo registrados no histórico clínico."""
    from prontuario.models import HistoricoClinico
    h = HistoricoClinico.objects.filter(paciente=paciente).first()
    if not h or not h.medicamentos_uso:
        return []
    return [(f'{p.strip()} (uso contínuo)', norm(p)) for p in re.split(r'[\n;,]+', h.medicamentos_uso) if p.strip()]


def verificar(itens):
    """itens: [(rótulo exibido, texto)] -> lista de alertas de interação."""
    itens = [(r, norm(t)) for r, t in itens if t]
    alertas, vistos = [], set()
    if len(itens) < 2:
        return alertas
    for it in InteracaoMedicamentosa.objects.filter(ativo=True):
        ta, tb = it.termos(it.substancia_a), it.termos(it.substancia_b)
        for i, (r1, t1) in enumerate(itens):
            for j, (r2, t2) in enumerate(itens):
                if i == j:
                    continue
                if _casa(ta, t1) and _casa(tb, t2):
                    chave = (it.pk, frozenset((r1, r2)))
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                    alertas.append({'a': r1, 'b': r2, 'gravidade': it.gravidade,
                                    'gravidade_txt': it.get_gravidade_display(), 'efeito': it.efeito,
                                    'conduta': it.conduta})
    ordem = {'contraindicada': 0, 'grave': 1, 'moderada': 2, 'leve': 3}
    return sorted(alertas, key=lambda a: ordem.get(a['gravidade'], 9))


def verificar_alergias(paciente, itens):
    """Compara as alergias registradas com o nome/princípio ativo dos itens."""
    from prontuario.models import HistoricoClinico
    h = HistoricoClinico.objects.filter(paciente=paciente).first()
    unicos = []
    for x in (paciente.alergias, h.alergias if h else ''):
        x = (x or '').strip()
        if x and norm(x) not in {norm(u) for u in unicos}:
            unicos.append(x)
    textos = ' ; '.join(unicos)
    termos = [t.strip() for t in re.split(r'[,;/\n]+| e ', norm(textos)) if len(t.strip()) > 3]
    conflitos = []
    for rotulo, texto in itens:
        t = norm(texto)
        achou = _casa(termos, t)
        if achou:
            conflitos.append({'item': rotulo, 'alergia': achou})
    return textos, conflitos
