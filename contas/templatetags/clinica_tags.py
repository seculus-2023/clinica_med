from django import template
from django.urls import reverse

from contas.crud import moeda as _moeda

register = template.Library()


@register.filter
def moeda(valor):
    return _moeda(valor)


@register.filter
def pode(perm, modulo):
    """{% if perm|pode:'agenda' %} -> possui ao menos visualização."""
    return bool(perm) and perm.get(modulo, 'nenhum') != 'nenhum'


@register.filter
def edita(perm, modulo):
    return bool(perm) and perm.get(modulo) == 'editar'


@register.simple_tag
def url_pk(nome, pk):
    return reverse(nome, args=[pk])


@register.filter
def get(d, chave):
    try:
        return d.get(chave)
    except AttributeError:
        return None


@register.filter
def so_digitos(valor):
    return ''.join(c for c in str(valor or '') if c.isdigit())


@register.filter
def whatsapp_numero(valor):
    d = ''.join(c for c in str(valor or '') if c.isdigit())
    if d and len(d) <= 11:
        d = '55' + d
    return d


@register.simple_tag(takes_context=True)
def ativo(context, *prefixos):
    path = context['request'].path
    return 'active' if any(path.startswith(p) for p in prefixos) else ''
