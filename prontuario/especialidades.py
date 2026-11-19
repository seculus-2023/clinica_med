"""Recursos por especialidade: curva de crescimento (pediatria) e odontograma (odontologia)."""
import json

from django import forms
from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from contas.crud import FormSimples
from contas.permissoes import acesso, tem_permissao

from .models import Atendimento, Odontograma, OdontogramaHistorico, ReferenciaCrescimento
from .views import _paciente, registrar

# ------------------------------------------------------------------ curva de crescimento
CAMPOS_CSV = ('sexo', 'indicador', 'idade_meses', 'p3', 'p15', 'p50', 'p85', 'p97')


def dados_crescimento(paciente):
    if not paciente.data_nascimento:
        return None
    pontos = {'peso': [], 'altura': [], 'imc': []}
    for a in Atendimento.objects.filter(paciente=paciente).order_by('data'):
        d = a.data.date()
        dias = (d - paciente.data_nascimento).days
        if dias < 0:
            continue
        meses = round(dias / 30.4375, 2)
        if a.peso:
            pontos['peso'].append([meses, float(a.peso)])
        if a.altura:
            pontos['altura'].append([meses, float(a.altura)])
        if a.imc:
            pontos['imc'].append([meses, float(a.imc)])
    sexo = paciente.sexo if paciente.sexo in ('M', 'F') else None
    refs = {}
    if sexo:
        for ind in pontos:
            lista = list(ReferenciaCrescimento.objects.filter(sexo=sexo, indicador=ind).values_list(
                'idade_meses', 'p3', 'p15', 'p50', 'p85', 'p97'))
            if lista:
                refs[ind] = [[i, *(float(v) if v is not None else None for v in vs)] for i, *vs in lista]
    return {'pontos': pontos, 'refs': refs, 'tem_dados': any(pontos.values())}


class ImportarCurvaForm(FormSimples):
    arquivo = forms.FileField(label='CSV de referência', help_text='Colunas: ' + ';'.join(CAMPOS_CSV) +
                              ' — sexo M/F; indicador peso, altura, imc ou pc; idade em meses.')


@acesso('prontuario', 'editar')
def importar_curvas(request):
    form = ImportarCurvaForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        from cadastros.importacao import decimal_br, ler_linhas, norm
        linhas = ler_linhas(form.cleaned_data['arquivo'])
        cab = [norm(c).lower() for c in next(linhas, [])]
        idx = {c: cab.index(c) for c in CAMPOS_CSV if c in cab}
        if not {'sexo', 'indicador', 'idade_meses', 'p3', 'p50', 'p97'} <= set(idx):
            messages.error(request, 'CSV sem as colunas obrigatórias: sexo, indicador, idade_meses, p3, p50, p97.')
            return redirect('prontuario:importar_curvas')
        n = 0
        for row in linhas:
            try:
                sexo, ind = str(row[idx['sexo']]).strip().upper()[:1], str(row[idx['indicador']]).strip().lower()
                if sexo not in 'MF' or ind not in dict(ReferenciaCrescimento.INDICADORES):
                    continue
                val = {c: decimal_br(row[idx[c]]) for c in ('p3', 'p15', 'p50', 'p85', 'p97') if c in idx}
                ReferenciaCrescimento.objects.update_or_create(
                    sexo=sexo, indicador=ind, idade_meses=int(float(str(row[idx['idade_meses']]).replace(',', '.'))),
                    defaults=val)
                n += 1
            except (IndexError, ValueError, TypeError):
                continue
        messages.success(request, f'{n} ponto(s) de referência importado(s).')
        return redirect('prontuario:importar_curvas')
    from django.db.models import Count
    resumo = ReferenciaCrescimento.objects.values('sexo', 'indicador').annotate(n=Count('id')).order_by('sexo', 'indicador')
    return render(request, 'prontuario/importar_curvas.html', {'form': form, 'resumo': resumo})


# ------------------------------------------------------------------ odontograma
SUPERIOR = [18, 17, 16, 15, 14, 13, 12, 11, 21, 22, 23, 24, 25, 26, 27, 28]
INFERIOR = [48, 47, 46, 45, 44, 43, 42, 41, 31, 32, 33, 34, 35, 36, 37, 38]
DECID_SUP = [55, 54, 53, 52, 51, 61, 62, 63, 64, 65]
DECID_INF = [85, 84, 83, 82, 81, 71, 72, 73, 74, 75]
SITUACOES = [('higido', 'Hígido', '#ffffff'), ('carie', 'Cárie', '#dc2626'), ('restaurado', 'Restaurado', '#2563eb'),
             ('canal', 'Tratamento de canal', '#7c3aed'), ('extracao', 'Extração indicada', '#f97316'),
             ('ausente', 'Ausente', '#9ca3af'), ('implante', 'Implante', '#16a34a'), ('protese', 'Prótese / coroa', '#ca8a04'),
             ('selante', 'Selante', '#0d9488'), ('fratura', 'Fratura', '#be185d')]


@acesso('prontuario')
def odontograma(request, pk):
    p = _paciente(request, pk)
    od, _ = Odontograma.objects.get_or_create(paciente=p, defaults={'clinica': request.clinica})
    return render(request, 'prontuario/odontograma.html', {
        'p': p, 'od': od, 'dados': json.dumps(od.dados), 'situacoes': SITUACOES, 'sit_json': json.dumps(SITUACOES),
        'arcadas': json.dumps({'sup': SUPERIOR, 'inf': INFERIOR, 'dsup': DECID_SUP, 'dinf': DECID_INF}),
        'historico': od.historico.select_related('usuario')[:50],
        'pode_editar': tem_permissao(request, 'prontuario', 'editar')})


@acesso('prontuario', 'editar')
@require_POST
def odontograma_salvar(request, pk):
    p = _paciente(request, pk)
    od, _ = Odontograma.objects.get_or_create(paciente=p, defaults={'clinica': request.clinica})
    try:
        novo = json.loads(request.body.decode() or '{}')
    except ValueError:
        return JsonResponse({'ok': False, 'erro': 'dados inválidos'}, status=400)
    dentes_validos = {str(d) for d in SUPERIOR + INFERIOR + DECID_SUP + DECID_INF}
    sits = {s[0] for s in SITUACOES}
    nomes = {s[0]: s[1] for s in SITUACOES}
    dados, mudancas = {}, []
    for dente, info in (novo.get('dados') or {}).items():
        if dente not in dentes_validos or not isinstance(info, dict):
            continue
        s = info.get('s') if info.get('s') in sits else 'higido'
        faces = {f: v for f, v in (info.get('f') or {}).items() if f in 'OMDVL' and len(f) == 1 and v in sits}
        dados[dente] = {'s': s, 'f': faces}
        antes = od.dados.get(dente) or {'s': 'higido', 'f': {}}
        if antes != dados[dente]:
            txt = nomes[s] + (' — faces ' + ', '.join(f'{f}: {nomes[v]}' for f, v in faces.items()) if faces else '')
            mudancas.append(OdontogramaHistorico(odontograma=od, dente=dente, descricao=txt[:200], usuario=request.user))
    for dente in set(od.dados) - set(dados):
        mudancas.append(OdontogramaHistorico(odontograma=od, dente=dente, descricao='Hígido', usuario=request.user))
    od.dados, od.atualizado_por = dados, request.user
    od.observacoes = str(novo.get('observacoes', od.observacoes))[:2000]
    od.save()
    OdontogramaHistorico.objects.bulk_create(mudancas)
    if mudancas:
        registrar(request, p, f'Odontograma atualizado ({len(mudancas)} dente(s))')
    return JsonResponse({'ok': True, 'mudancas': len(mudancas)})
