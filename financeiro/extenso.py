"""Valor por extenso em português (para recibos)."""
from decimal import ROUND_HALF_UP, Decimal

UNID = ['zero', 'um', 'dois', 'três', 'quatro', 'cinco', 'seis', 'sete', 'oito', 'nove', 'dez', 'onze', 'doze',
        'treze', 'quatorze', 'quinze', 'dezesseis', 'dezessete', 'dezoito', 'dezenove']
DEZ = ['', '', 'vinte', 'trinta', 'quarenta', 'cinquenta', 'sessenta', 'setenta', 'oitenta', 'noventa']
CEM = ['', 'cento', 'duzentos', 'trezentos', 'quatrocentos', 'quinhentos', 'seiscentos', 'setecentos', 'oitocentos',
       'novecentos']


def _ate_mil(n):
    if n == 0:
        return ''
    if n == 100:
        return 'cem'
    partes = []
    c, r = divmod(n, 100)
    if c:
        partes.append(CEM[c])
    if r:
        if r < 20:
            partes.append(UNID[r])
        else:
            d, u = divmod(r, 10)
            partes.append(DEZ[d] + (f' e {UNID[u]}' if u else ''))
    return ' e '.join(partes)


def _inteiro(n):
    if n == 0:
        return 'zero'
    grupos = []
    for nome_s, nome_p, valor in (('bilhão', 'bilhões', 10 ** 9), ('milhão', 'milhões', 10 ** 6), ('mil', 'mil', 1000)):
        q, n = divmod(n, valor)
        if q:
            grupos.append('mil' if (valor == 1000 and q == 1) else f'{_ate_mil(q) if q < 1000 else _inteiro(q)} '
                                                                    f'{nome_s if q == 1 else nome_p}')
    if n:
        grupos.append(_ate_mil(n))
    if len(grupos) > 1 and (n < 100 or n % 100 == 0) and n:
        return ' '.join(grupos[:-1]) + ' e ' + grupos[-1]
    return ' '.join(grupos)


def por_extenso(valor):
    v = Decimal(valor or 0).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    reais, cent = int(v), int((v - int(v)) * 100)
    partes = []
    if reais:
        txt = _inteiro(reais)
        if reais % 1_000_000 == 0:
            txt += ' de'
        partes.append(f"{txt} {'real' if reais == 1 else 'reais'}")
    if cent:
        partes.append(f"{_ate_mil(cent)} {'centavo' if cent == 1 else 'centavos'}")
    return ' e '.join(partes) if partes else 'zero real'
