import json
import mimetypes

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from agenda.models import Agendamento
from cadastros.models import Cid, Medico, Paciente
from contas.crud import Autocomplete, ClinicaModelForm, Crud, FormSimples, estilizar_campos
from contas.permissoes import acesso, medico_restrito, tem_permissao

from .models import (AcessoProntuario, Adendo, Anexo, Atendimento, ExameLaboratorial, HistoricoClinico,
                     ModeloProntuario, ResultadoExame)


# ------------------------------------------------------------------ formulários
class HistoricoForm(ClinicaModelForm):
    class Meta:
        model = HistoricoClinico
        exclude = ['paciente']


class AtendimentoForm(ClinicaModelForm):
    cids_secundarios = forms.ModelMultipleChoiceField(queryset=Cid.objects.all(), required=False,
                                                      widget=forms.MultipleHiddenInput)

    class Meta:
        model = Atendimento
        exclude = ['paciente']
        widgets = {'cid_principal': Autocomplete('cadastros:api_cid', Cid)}

    def __init__(self, *args, medico_fixo=None, modelo=None, **kwargs):
        super().__init__(*args, **kwargs)
        if medico_fixo:
            self.fields['medico'].queryset = Medico.objects.filter(pk=medico_fixo.pk)
            self.fields['medico'].initial = medico_fixo.pk
        self.modelo_obj = modelo
        self.fields['modelo'].queryset = ModeloProntuario.objects.filter(clinica=self.clinica, ativo=True)
        self.fields['modelo'].required = False
        self.fields['modelo'].empty_label = 'Padrão (SOAP)'
        self.initial['modelo'] = modelo.pk if modelo else None
        self._campos = modelo.campos() if modelo else []
        salvos = {}
        if self.instance.pk and modelo and self.instance.modelo_id == modelo.pk:
            salvos = {c['chave']: c.get('valor') for c in (self.instance.respostas or {}).get('campos', [])}
        escala = [('', '-')] + [(str(i), str(i)) for i in range(11)]
        for c in self._campos:
            t, nome = c['tipo'], f"mp_{c['chave']}"
            if t == 'texto_longo':
                f = forms.CharField(widget=forms.Textarea(attrs={'rows': 2}))
            elif t == 'numero':
                f = forms.DecimalField(decimal_places=3, max_digits=12)
            elif t == 'sim_nao':
                f = forms.ChoiceField(choices=[('', '-'), ('Sim', 'Sim'), ('Não', 'Não')])
            elif t == 'opcoes':
                f = forms.ChoiceField(choices=[('', '-')] + [(o, o) for o in c['opcoes']])
            elif t == 'escala':
                f = forms.ChoiceField(choices=escala)
            else:
                f = forms.CharField(max_length=300)
            f.label, f.required, f.initial = c['rotulo'], False, salvos.get(c['chave'])
            self.fields[nome] = f
        estilizar_campos(self)

    def _secao(self, s):
        return [self[f"mp_{c['chave']}"] for c in self._campos if c['secao'] == s]

    @property
    def campos_S(self):
        return self._secao('S')

    @property
    def campos_O(self):
        return self._secao('O')

    @property
    def campos_A(self):
        return self._secao('A')

    @property
    def campos_P(self):
        return self._secao('P')

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.modelo = self.modelo_obj
        def texto(v):
            if v in (None, ''):
                return ''
            s = f'{v:f}' if hasattr(v, 'quantize') else str(v)
            return s.rstrip('0').rstrip('.') if hasattr(v, 'quantize') and '.' in s else s
        obj.respostas = {'modelo': str(self.modelo_obj) if self.modelo_obj else '', 'campos': [
            {'chave': c['chave'], 'secao': c['secao'], 'rotulo': c['rotulo'],
             'valor': texto(self.cleaned_data.get(f"mp_{c['chave']}"))} for c in self._campos]}
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class AnexoForm(ClinicaModelForm):
    class Meta:
        model = Anexo
        fields = ['tipo', 'titulo', 'data', 'arquivo', 'resultado', 'atendimento']

    def __init__(self, *args, paciente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['atendimento'].queryset = Atendimento.objects.filter(paciente=paciente)
        self.fields['atendimento'].required = False

    def clean_arquivo(self):
        f = self.cleaned_data.get('arquivo')
        if f and hasattr(f, 'size') and f.size > 20 * 1024 * 1024:
            raise forms.ValidationError('Arquivo maior que 20 MB.')
        if f and hasattr(f, 'name') and not f.name.lower().endswith(
                ('.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.doc', '.docx', '.txt', '.dcm')):
            raise forms.ValidationError('Tipo de arquivo não permitido.')
        return f


# ------------------------------------------------------------------ utilidades
def registrar(request, paciente, acao):
    ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
    AcessoProntuario.objects.create(clinica=request.clinica, paciente=paciente, usuario=request.user, acao=acao,
                                    ip=ip or None)


def pacientes_permitidos(request):
    qs = Paciente.objects.filter(clinica=request.clinica)
    med = medico_restrito(request)
    if med:  # médico com "apenas própria agenda" só consulta pacientes que atendeu/agendou
        qs = qs.filter(Q(agendamentos__medico=med) | Q(atendimentos__medico=med)).distinct()
    return qs


def _paciente(request, pk):
    return get_object_or_404(pacientes_permitidos(request), pk=pk)


def _medico_do_usuario(request):
    return Medico.objects.filter(clinica=request.clinica, usuario=request.user, ativo=True).first()


def _contexto_prontuario(request, p):
    hist = HistoricoClinico.objects.filter(paciente=p).first()
    atendimentos = list(Atendimento.objects.filter(paciente=p).select_related(
        'medico', 'cid_principal', 'agendamento').prefetch_related('cids_secundarios', 'adendos__autor', 'anexos'))
    from documentos.models import Documento
    documentos = Documento.objects.filter(paciente=p).select_related('medico').prefetch_related('itens')
    anexos = Anexo.objects.filter(paciente=p).select_related('atendimento')
    agendamentos = Agendamento.objects.filter(paciente=p).select_related('medico', 'tipo').order_by('-inicio')
    linha = [('atendimento', a.data, a) for a in atendimentos]
    linha += [('documento', d.data, d) for d in documentos]
    linha += [('anexo', timezone.make_aware(timezone.datetime.combine(x.data, timezone.datetime.min.time())), x)
              for x in anexos]
    linha.sort(key=lambda t: t[1], reverse=True)
    vitais = [a for a in reversed(atendimentos) if a.tem_sinais_vitais]
    grafico = {
        'datas': [timezone.localtime(a.data).strftime('%d/%m/%y') for a in vitais],
        'peso': [float(a.peso) if a.peso else None for a in vitais],
        'pas': [a.pa_sistolica for a in vitais], 'pad': [a.pa_diastolica for a in vitais],
        'glicemia': [a.glicemia for a in vitais],
    }
    cids = {}
    for a in atendimentos:
        for c in ([a.cid_principal] if a.cid_principal else []) + list(a.cids_secundarios.all()):
            item = cids.setdefault(c.codigo, {'cid': c, 'n': 0, 'ultimo': a.data})
            item['n'] += 1
    lab = comparativo_laboratorial(p)
    return {
        'lab': lab, 'lab_series': json.dumps(lab['series']),
        'p': p, 'hist': hist, 'atendimentos': atendimentos, 'documentos': documentos, 'anexos': anexos,
        'agendamentos': agendamentos[:50], 'linha': linha, 'grafico': json.dumps(grafico), 'tem_vitais': bool(vitais),
        'ultimo_vital': vitais[-1] if vitais else None, 'cids': sorted(cids.values(), key=lambda x: -x['n']),
        'proximos': agendamentos.filter(inicio__gte=timezone.now()).exclude(status='cancelado').order_by('inicio')[:3],
    }


# ------------------------------------------------------------------ consulta (somente leitura)
@acesso('prontuario')
def consulta(request):
    """Tela de consulta de prontuários - acesso separado e somente leitura."""
    q = request.GET.get('q', '').strip()
    qs = pacientes_permitidos(request).annotate(ult=Max('atendimentos__data'), n=Count('atendimentos', distinct=True))
    if q:
        qs = qs.filter(Q(nome__icontains=q) | Q(cpf__icontains=q) | Q(celular__icontains=q))
    else:
        qs = qs.filter(ult__isnull=False)
    return render(request, 'prontuario/consulta.html', {
        'pacientes': qs.order_by('-ult', 'nome')[:60], 'q': q, 'modo_consulta': True})


@acesso('prontuario')
def consulta_paciente(request, pk):
    p = _paciente(request, pk)
    registrar(request, p, 'Consulta (somente leitura)')
    ctx = _contexto_prontuario(request, p)
    ctx.update({'modo_consulta': True, 'pode_editar': False})
    return render(request, 'prontuario/paciente.html', ctx)


# ------------------------------------------------------------------ prontuário completo (registro)
@acesso('prontuario')
def paciente(request, pk):
    if not tem_permissao(request, 'prontuario', 'editar'):
        return redirect('prontuario:consulta_paciente', pk)
    p = _paciente(request, pk)
    registrar(request, p, 'Visualização')
    ctx = _contexto_prontuario(request, p)
    ctx.update({'modo_consulta': False, 'pode_editar': True,
                'pode_documentos': tem_permissao(request, 'documentos', 'editar'),
                'pode_agendar': tem_permissao(request, 'agenda', 'editar')})
    return render(request, 'prontuario/paciente.html', ctx)


@acesso('prontuario', 'editar')
def historico(request, pk):
    p = _paciente(request, pk)
    hist = HistoricoClinico.objects.filter(paciente=p).first()
    form = HistoricoForm(request.POST or None, instance=hist, clinica=request.clinica,
                         initial={'alergias': p.alergias} if not hist else None)
    if request.method == 'POST' and form.is_valid():
        h = form.save(commit=False)
        h.paciente, h.clinica, h.atualizado_por = p, request.clinica, request.user
        h.save()
        if h.alergias != p.alergias:
            p.alergias = h.alergias
            p.save(update_fields=['alergias', 'atualizado_em'])
        registrar(request, p, 'Histórico clínico atualizado')
        messages.success(request, 'Histórico clínico salvo.')
        return redirect('prontuario:paciente', p.pk)
    return render(request, 'prontuario/historico_form.html', {'form': form, 'p': p})


@acesso('prontuario', 'editar')
def atendimento_novo(request, pk):
    p = _paciente(request, pk)
    ag = None
    if request.GET.get('agendamento'):
        ag = get_object_or_404(Agendamento, pk=request.GET['agendamento'], clinica=request.clinica, paciente=p)
        existente = Atendimento.objects.filter(agendamento=ag).first()
        if existente:
            return redirect('prontuario:atendimento', existente.pk)
    medico = _medico_do_usuario(request)
    inicial = {'tipo': 'consulta'}
    if ag:
        medico = ag.medico if not medico else medico
        inicial.update({'medico': ag.medico_id, 'tipo': 'sessao' if ag.pacote_id else 'consulta'})
    elif medico:
        inicial['medico'] = medico.pk
    ultimo = Atendimento.objects.filter(paciente=p, altura__isnull=False).first()
    if ultimo:
        inicial['altura'] = ultimo.altura
    modelo = _escolher_modelo(request, medico)
    if modelo and request.method == 'GET':
        inicial.update({'hda': modelo.queixa_padrao, 'exame_fisico': modelo.exame_fisico_padrao,
                        'conduta': modelo.conduta_padrao})
    form = AtendimentoForm(request.POST or None, initial=inicial, clinica=request.clinica,
                           medico_fixo=medico_restrito(request), modelo=modelo)
    if request.method == 'POST' and form.is_valid():
        a = form.save(commit=False)
        a.clinica, a.paciente, a.agendamento, a.criado_por = request.clinica, p, ag, request.user
        a.save()
        form.save_m2m()
        if ag and ag.status in ('agendado', 'confirmado', 'aguardando'):
            from agenda.services import mudar_status
            mudar_status(ag, 'em_atendimento')
        registrar(request, p, 'Atendimento registrado')
        _alerta_retorno(a)
        if request.POST.get('finalizar'):
            return _finalizar(request, a)
        messages.success(request, 'Atendimento salvo (em andamento). Finalize para assinar o registro.')
        return redirect('prontuario:atendimento', a.pk)
    return render(request, 'prontuario/atendimento_form.html', {'form': form, 'p': p, 'ag': ag,
                                                                'cids_sel': []})


@acesso('prontuario', 'editar')
def atendimento_editar(request, pk):
    a = get_object_or_404(Atendimento.objects.select_related('paciente', 'medico'), pk=pk, clinica=request.clinica)
    _paciente(request, a.paciente_id)
    if not a.pode_editar(request.user):
        messages.warning(request, 'Atendimento finalizado ou de outro profissional: use um adendo para complementar.')
        return redirect('prontuario:atendimento', a.pk)
    form = AtendimentoForm(request.POST or None, instance=a, clinica=request.clinica,
                           medico_fixo=medico_restrito(request), modelo=_escolher_modelo(request, a.medico, a))
    if request.method == 'POST' and form.is_valid():
        form.save()
        registrar(request, a.paciente, 'Atendimento alterado')
        _alerta_retorno(a)
        if request.POST.get('finalizar'):
            return _finalizar(request, a)
        messages.success(request, 'Atendimento atualizado.')
        return redirect('prontuario:atendimento', a.pk)
    return render(request, 'prontuario/atendimento_form.html', {
        'form': form, 'p': a.paciente, 'obj': a, 'ag': a.agendamento, 'cids_sel': list(a.cids_secundarios.all())})


def _escolher_modelo(request, medico, atendimento=None):
    qs = ModeloProntuario.objects.filter(clinica=request.clinica, ativo=True)
    escolhido = request.POST.get('modelo') if request.method == 'POST' else request.GET.get('modelo')
    if escolhido is not None:
        return qs.filter(pk=escolhido).first() if escolhido not in ('', '0') else None
    if atendimento is not None:
        return atendimento.modelo
    if medico:
        return qs.filter(especialidade__in=medico.especialidades.all()).first()
    return None


def _alerta_retorno(a):
    if a.retorno_em:
        from callcenter.services import agendar_retorno
        agendar_retorno(a.paciente, a.medico, a.retorno_em, a.agendamento, '(definido no prontuário)')


def _finalizar(request, a):
    a.status, a.finalizado_em = 'finalizado', timezone.now()
    a.save(update_fields=['status', 'finalizado_em', 'atualizado_em'])
    if a.agendamento and a.agendamento.status not in ('concluido', 'cancelado'):
        from agenda.services import mudar_status
        mudar_status(a.agendamento, 'concluido')
    registrar(request, a.paciente, 'Atendimento finalizado/assinado')
    messages.success(request, 'Atendimento finalizado e assinado. A partir de agora só é possível incluir adendos.')
    return redirect('prontuario:atendimento', a.pk)


@acesso('prontuario', 'editar')
@require_POST
def atendimento_finalizar(request, pk):
    a = get_object_or_404(Atendimento, pk=pk, clinica=request.clinica)
    if not a.pode_editar(request.user):
        raise PermissionDenied
    return _finalizar(request, a)


@acesso('prontuario')
def atendimento(request, pk):
    a = get_object_or_404(Atendimento.objects.select_related('paciente', 'medico', 'cid_principal', 'agendamento'),
                          pk=pk, clinica=request.clinica)
    _paciente(request, a.paciente_id)
    editar = tem_permissao(request, 'prontuario', 'editar')
    if request.method == 'POST':
        if not editar:
            raise PermissionDenied
        texto = request.POST.get('adendo', '').strip()
        if texto:
            Adendo.objects.create(atendimento=a, texto=texto, autor=request.user)
            registrar(request, a.paciente, 'Adendo incluído')
            messages.success(request, 'Adendo incluído.')
        return redirect('prontuario:atendimento', a.pk)
    registrar(request, a.paciente, 'Visualização de atendimento')
    from documentos.models import Documento
    return render(request, 'prontuario/atendimento.html', {
        'a': a, 'p': a.paciente, 'resp': a.respostas_por_secao(),
        'pode_editar_registro': editar and a.pode_editar(request.user),
        'pode_adendo': editar, 'modo_consulta': not editar,
        'ver_privado': request.user.pk in (a.criado_por_id, a.medico.usuario_id),
        'documentos': Documento.objects.filter(Q(atendimento=a) | Q(agendamento=a.agendamento) if a.agendamento
                                               else Q(atendimento=a)),
        'pode_documentos': tem_permissao(request, 'documentos', 'editar')})


@acesso('prontuario', 'editar')
def iniciar(request, agendamento_pk):
    ag = get_object_or_404(Agendamento, pk=agendamento_pk, clinica=request.clinica)
    return redirect(f"{_url('prontuario:atendimento_novo', ag.paciente_id)}?agendamento={ag.pk}")


def _url(nome, *args):
    from django.urls import reverse
    return reverse(nome, args=args)


# ------------------------------------------------------------------ anexos
@acesso('prontuario', 'editar')
def anexo_novo(request, pk):
    p = _paciente(request, pk)
    inicial = {'atendimento': request.GET.get('atendimento')} if request.GET.get('atendimento') else {}
    form = AnexoForm(request.POST or None, request.FILES or None, initial=inicial, clinica=request.clinica,
                     paciente=p)
    if request.method == 'POST' and form.is_valid():
        x = form.save(commit=False)
        x.clinica, x.paciente, x.enviado_por = request.clinica, p, request.user
        x.save()
        registrar(request, p, f'Anexo incluído: {x.titulo}')
        messages.success(request, 'Exame/anexo incluído.')
        return redirect(f"{_url('prontuario:paciente', p.pk)}#exames")
    return render(request, 'form_simples.html', {'form': form, 'titulo': f'Novo exame / anexo - {p.nome}',
                                                 'multipart': True,
                                                 'voltar_url': _url('prontuario:paciente', p.pk)})


@acesso('prontuario')
def anexo_arquivo(request, pk):
    x = get_object_or_404(Anexo, pk=pk, clinica=request.clinica)
    _paciente(request, x.paciente_id)
    if not x.arquivo:
        raise Http404
    registrar(request, x.paciente, f'Download de anexo: {x.titulo}')
    tipo = mimetypes.guess_type(x.nome_arquivo)[0] or 'application/octet-stream'
    resp = FileResponse(x.arquivo.open('rb'), content_type=tipo)
    resp['Content-Disposition'] = f'inline; filename="{x.nome_arquivo}"'
    resp['Cache-Control'] = 'private, no-store'
    return resp


# ------------------------------------------------------------------ impressão e auditoria
@acesso('prontuario')
def imprimir(request, pk):
    p = _paciente(request, pk)
    registrar(request, p, 'Impressão do prontuário')
    ctx = _contexto_prontuario(request, p)
    ctx['c'] = request.clinica
    ctx['agora'] = timezone.localtime()
    return render(request, 'prontuario/imprimir.html', ctx)


@acesso('administrativo')
def auditoria(request, pk):
    p = get_object_or_404(Paciente, pk=pk, clinica=request.clinica)
    return render(request, 'prontuario/auditoria.html', {
        'p': p, 'acessos': AcessoProntuario.objects.filter(paciente=p).select_related('usuario')[:300]})


# ------------------------------------------------------------------ gravação da teleconsulta
@acesso('prontuario', 'editar')
@require_POST
def gravacao(request, agendamento_pk):
    from django.core.files.base import File
    from django.http import JsonResponse
    ag = get_object_or_404(Agendamento, pk=agendamento_pk, clinica=request.clinica)
    if not ag.teleconsulta or not ag.tele_autoriza_gravacao:
        return JsonResponse({'ok': False, 'erro': 'Gravação não autorizada pelo paciente.'}, status=403)
    arq = request.FILES.get('video')
    if not arq:
        return JsonResponse({'ok': False, 'erro': 'Arquivo não recebido.'}, status=400)
    if arq.size > 1024 * 1024 * 1024:
        return JsonResponse({'ok': False, 'erro': 'Gravação maior que 1 GB.'}, status=400)
    agora = timezone.localtime()
    x = Anexo(clinica=request.clinica, paciente=ag.paciente, atendimento=Atendimento.objects.filter(agendamento=ag).first(),
              tipo='video', titulo=f'Gravação da teleconsulta {agora:%d/%m/%Y %H:%M}', enviado_por=request.user,
              resultado=f'Teleconsulta com {ag.medico}. Gravação autorizada pelo paciente em '
                        f'{timezone.localtime(ag.tele_consentimento_em):%d/%m/%Y %H:%M} (IP {ag.tele_consentimento_ip}).')
    x.arquivo.save(f'teleconsulta_{ag.pk}_{agora:%Y%m%d%H%M%S}.webm', File(arq), save=False)
    x.save()
    registrar(request, ag.paciente, 'Gravação de teleconsulta salva')
    return JsonResponse({'ok': True, 'anexo': x.pk})


# ------------------------------------------------------------------ modelos de prontuário
class ModeloForm(ClinicaModelForm):
    class Meta:
        model = ModeloProntuario
        exclude = []
        widgets = {'definicao': forms.Textarea(attrs={'rows': 10, 'style': 'font-family: monospace;'})}


class ModeloCrud(Crud):
    model, form_class = ModeloProntuario, ModeloForm
    modulo = 'prontuario'
    nome, nome_plural, url, icone = 'Modelo', 'Modelos de prontuário por especialidade', 'prontuario:modelo', \
        'bi-ui-checks'
    descricao = ('Campos específicos por especialidade (ex.: fisioterapia, cardiologia) e textos padrão. '
                 'Cada linha: Seção | Rótulo | tipo | opções — tipos: texto, texto_longo, numero, sim_nao, opcoes, escala.')
    colunas = [('nome', 'Modelo'), ('especialidade', 'Especialidade'), ('ativo', 'Ativo')]
    busca = ['nome']
    acoes_topo = [('prontuario:modelos_padrao', 'bi-magic', 'Criar modelos padrão')]


@acesso('prontuario', 'editar')
@require_POST
def modelos_padrao(request):
    from .padroes import criar_modelos_padrao
    n = criar_modelos_padrao(request.clinica)
    messages.success(request, f'{n} modelo(s) criado(s).')
    return redirect('prontuario:modelo_list')


# ------------------------------------------------------------------ exames laboratoriais
class ExameForm(ClinicaModelForm):
    class Meta:
        model = ExameLaboratorial
        exclude = []


class ExameCrud(Crud):
    model, form_class = ExameLaboratorial, ExameForm
    modulo = 'prontuario'
    nome, nome_plural, url, icone = 'Exame', 'Catálogo de exames laboratoriais', 'prontuario:exame', 'bi-droplet-half'
    descricao = 'Unidades e faixas de referência usadas no gráfico comparativo (ajuste conforme o laboratório).'
    colunas = [('grupo', 'Grupo'), ('nome', 'Exame'), ('unidade', 'Unidade'), ('referencia', 'Referência'),
               ('ativo', 'Ativo')]
    busca = ['nome', 'grupo']
    acoes_topo = [('prontuario:exames_padrao', 'bi-magic', 'Criar catálogo padrão')]


@acesso('prontuario', 'editar')
@require_POST
def exames_padrao(request):
    from .padroes import criar_exames_padrao
    n = criar_exames_padrao(request.clinica)
    messages.success(request, f'{n} exame(s) adicionado(s) ao catálogo.')
    return redirect('prontuario:exame_list')


@acesso('prontuario', 'editar')
def resultados_lancar(request, pk):
    from decimal import Decimal, InvalidOperation
    p = _paciente(request, pk)
    exames = list(ExameLaboratorial.objects.filter(clinica=request.clinica, ativo=True))
    if not exames:
        from .padroes import criar_exames_padrao
        criar_exames_padrao(request.clinica)
        exames = list(ExameLaboratorial.objects.filter(clinica=request.clinica, ativo=True))
    anexos = Anexo.objects.filter(paciente=p, tipo='laboratorio')
    erros = []
    if request.method == 'POST':
        from django.utils.dateparse import parse_date
        data = parse_date(request.POST.get('data', '')) or timezone.localdate()
        anexo = anexos.filter(pk=request.POST.get('anexo') or 0).first()
        n = 0
        for e in exames:
            bruto = (request.POST.get(f'ex_{e.pk}') or '').strip().replace(',', '.')
            if not bruto:
                continue
            try:
                valor = Decimal(bruto)
            except InvalidOperation:
                erros.append(f'{e.nome}: valor inválido "{bruto}"')
                continue
            ResultadoExame.objects.update_or_create(
                clinica=request.clinica, paciente=p, exame=e, data=data,
                defaults={'valor': valor, 'anexo': anexo, 'lancado_por': request.user})
            n += 1
        if not erros:
            registrar(request, p, f'{n} resultado(s) de exame lançado(s)')
            messages.success(request, f'{n} resultado(s) lançado(s) em {data:%d/%m/%Y}.')
            return redirect(f"{_url('prontuario:paciente', p.pk)}#laboratorio")
    grupos = {}
    for e in exames:
        e.valor_post = request.POST.get(f'ex_{e.pk}', '')
        grupos.setdefault(e.grupo or 'Outros', []).append(e)
    return render(request, 'prontuario/resultados_form.html', {
        'p': p, 'hist': HistoricoClinico.objects.filter(paciente=p).first(), 'grupos': grupos, 'anexos': anexos,
        'erros': erros, 'hoje': timezone.localdate(), 'post': request.POST})


def comparativo_laboratorial(paciente):
    """Matriz exames x datas + séries para gráfico."""
    res = list(ResultadoExame.objects.filter(paciente=paciente).select_related('exame').order_by('data'))
    datas = sorted({r.data for r in res})
    por_exame = {}
    for r in res:
        por_exame.setdefault(r.exame, {})[r.data] = r
    linhas, series = [], {}
    for exame in sorted(por_exame, key=lambda e: (e.grupo, e.nome)):
        valores = por_exame[exame]
        celulas = [valores.get(d) for d in datas]
        ordenados = [valores[d] for d in sorted(valores)]
        tendencia = ''
        if len(ordenados) >= 2:
            a, b = ordenados[-2].valor, ordenados[-1].valor
            tendencia = 'sobe' if b > a else ('desce' if b < a else 'igual')
        linhas.append({'exame': exame, 'celulas': celulas, 'tendencia': tendencia})
        series[exame.pk] = {'nome': str(exame), 'min': float(exame.ref_min) if exame.ref_min is not None else None,
                            'max': float(exame.ref_max) if exame.ref_max is not None else None,
                            'pontos': [[r.data.strftime('%d/%m/%y'), float(r.valor)] for r in ordenados]}
    return {'datas': datas, 'linhas': linhas, 'series': series}
