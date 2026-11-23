from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from contas.crud import Autocomplete, ClinicaModelForm, Crud, FormSimples, moeda
from contas.permissoes import acesso, tem_permissao

from . import importacao
from .models import (Cid, Especialidade, HorarioAtendimento, InteracaoMedicamentosa, Medicamento, Medico,
                     Paciente, Procedimento, TipoAtendimento)

Usuario = get_user_model()


class PacienteForm(ClinicaModelForm):
    class Meta:
        model = Paciente
        exclude = []

    def clean(self):
        d = super().clean()
        if not d.get('acesso_app'):
            return d
        digitos = lambda s: ''.join(c for c in str(s or '') if c.isdigit())
        cpf, nascimento = digitos(d.get('cpf')), d.get('data_nascimento')
        if len(cpf) != 11:
            self.add_error('cpf', 'Informe o CPF com 11 dígitos para liberar o app.')
        if not nascimento:
            self.add_error('data_nascimento', 'Informe a data de nascimento para liberar o app.')
        if not (d.get('celular') or d.get('email')):
            self.add_error('celular', 'Informe celular ou e-mail para o paciente receber o código de acesso.')
        if len(cpf) == 11 and nascimento:
            outros = Paciente.objects.filter(clinica=self.clinica, ativo=True, acesso_app=True,
                                             data_nascimento=nascimento).exclude(pk=self.instance.pk)
            if any(digitos(o.cpf) == cpf for o in outros):
                self.add_error('cpf', 'Já existe paciente com acesso ao app com este CPF e nascimento.')
        return d


class AssinaturaWidget(forms.ClearableFileInput):
    template_name = 'widgets/assinatura.html'
    url_preview = ''

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        ctx['widget']['url_preview'] = self.url_preview
        return ctx


class MedicoForm(ClinicaModelForm):
    assinatura_desenho = forms.CharField(required=False, widget=forms.HiddenInput)

    class Meta:
        model = Medico
        exclude = []
        widgets = {'cor': forms.TextInput(attrs={'type': 'color'}),
                   'especialidades': forms.CheckboxSelectMultiple, 'assinatura': AssinaturaWidget}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['usuario'].queryset = Usuario.objects.filter(vinculos__clinica=self.clinica).distinct()
        self.fields['cor'].widget.attrs['class'] = 'form-control form-control-color'
        if self.instance.pk and self.instance.assinatura:
            from django.urls import reverse
            self.fields['assinatura'].widget.url_preview = reverse('documentos:medico_assinatura',
                                                                   args=[self.instance.pk])
        self.fields['assinatura_desenho'].label = ''

    def clean_assinatura(self):
        f = self.cleaned_data.get('assinatura')
        if f and hasattr(f, 'size') and f.size > 2 * 1024 * 1024:
            raise forms.ValidationError('Imagem da assinatura maior que 2 MB.')
        return f

    def clean_assinatura_desenho(self):
        v = self.cleaned_data.get('assinatura_desenho') or ''
        if v and (not v.startswith('data:image/png;base64,') or len(v) > 3_000_000):
            raise forms.ValidationError('Desenho de assinatura inválido.')
        return v

    def save(self, commit=True):
        obj = super().save(commit=False)
        desenho = self.cleaned_data.get('assinatura_desenho')
        if desenho:
            import base64
            from django.core.files.base import ContentFile
            obj.assinatura.save(f'assinatura_{obj.pk or "nova"}.png',
                                ContentFile(base64.b64decode(desenho.split(',', 1)[1])), save=False)
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class EspecialidadeForm(ClinicaModelForm):
    class Meta:
        model = Especialidade
        exclude = []


class MedicamentoForm(ClinicaModelForm):
    class Meta:
        model = Medicamento
        exclude = []


class ProcedimentoForm(ClinicaModelForm):
    class Meta:
        model = Procedimento
        exclude = []


class CidForm(ClinicaModelForm):
    class Meta:
        model = Cid
        fields = ['versao', 'codigo', 'nome', 'sexo', 'ativo']


class InteracaoForm(ClinicaModelForm):
    class Meta:
        model = InteracaoMedicamentosa
        exclude = []


class TipoAtendimentoForm(ClinicaModelForm):
    class Meta:
        model = TipoAtendimento
        exclude = []
        widgets = {'procedimento': Autocomplete('cadastros:api_procedimentos', Procedimento)}


class HorarioForm(ClinicaModelForm):
    class Meta:
        model = HorarioAtendimento
        exclude = []

    def clean(self):
        d = super().clean()
        if d.get('inicio') and d.get('fim') and d['fim'] <= d['inicio']:
            self.add_error('fim', 'O horário final deve ser maior que o inicial.')
        return d


ATIVO = [('True', 'Ativos'), ('False', 'Inativos')]


class HorarioCrud(Crud):
    model, form_class = HorarioAtendimento, HorarioForm
    nome, nome_plural, url, icone = 'Horário', 'Horários de atendimento', 'cadastros:horario', 'bi-clock'
    descricao = 'Grade semanal de cada profissional (usada no agendamento online e na taxa de ocupação).'
    colunas = [('medico', 'Profissional'), ('dia_semana', 'Dia'), ('inicio', 'Das'), ('fim', 'Até')]
    busca = ['medico__nome']

    @classmethod
    def queryset(cls, request):
        return HorarioAtendimento.objects.filter(clinica=request.clinica).select_related('medico')


class PacienteCrud(Crud):
    model, form_class = Paciente, PacienteForm
    nome, nome_plural, url, icone = 'Paciente', 'Pacientes', 'cadastros:paciente', 'bi-person-heart'
    colunas = [('nome', 'Nome'), ('cpf', 'CPF'), ('celular', 'Celular'), ('idade', 'Idade'),
               ('convenio', 'Convênio'), ('acesso_app', 'App'), ('ativo', 'Ativo')]
    busca = ['nome', 'cpf', 'celular', 'email']
    filtros = [('ativo', 'Situação', ATIVO)]
    acoes_linha = [('prontuario:paciente', 'bi-journal-medical', 'Prontuário'),
                   ('cadastros:paciente_ficha', 'bi-folder2-open', 'Ficha do paciente')]


class MedicoCrud(Crud):
    @classmethod
    def antes_salvar(cls, request, obj, form):
        from django.conf import settings
        if not obj.pk and settings.SAAS_ATIVO and not request.user.is_superuser:
            a = getattr(request.clinica, 'assinatura', None)
            if a and a.limite_atingido('medicos'):
                from django.core.exceptions import PermissionDenied
                raise PermissionDenied('Limite de profissionais do plano atingido.')

    model, form_class = Medico, MedicoForm
    nome, nome_plural, url, icone = 'Médico', 'Médicos / Profissionais', 'cadastros:medico', 'bi-person-badge'
    colunas = [('nome', 'Nome'), ('registro_completo', 'Registro'), ('especialidades', 'Especialidades'),
               ('celular', 'Celular'), ('usuario', 'Usuário'), ('ativo', 'Ativo')]
    busca = ['nome', 'registro', 'email']
    filtros = [('ativo', 'Situação', ATIVO)]


class EspecialidadeCrud(Crud):
    model, form_class = Especialidade, EspecialidadeForm
    nome, nome_plural, url, icone = 'Especialidade', 'Especialidades', 'cadastros:especialidade', 'bi-diagram-3'
    colunas = [('nome', 'Nome'), ('descricao', 'Descrição'), ('ativo', 'Ativo')]
    busca = ['nome']


class MedicamentoCrud(Crud):
    model, form_class = Medicamento, MedicamentoForm
    nome, nome_plural, url, icone = 'Medicamento', 'Tabela de medicamentos', 'cadastros:medicamento', 'bi-capsule'
    descricao = 'Cadastro manual ou importado da tabela CMED / ANVISA (preços máximos PF e PMC).'
    colunas = [('nome', 'Produto'), ('principio_ativo', 'Substância'), ('apresentacao', 'Apresentação'),
               ('laboratorio', 'Laboratório'), ('tipo_produto', 'Tipo'), ('preco_fabrica', 'PF', 'moeda'),
               ('preco_maximo_consumidor', 'PMC', 'moeda'), ('controlado', 'Controlado')]
    busca = ['nome', 'principio_ativo', 'ean', 'registro_anvisa', 'laboratorio']
    filtros = [('origem', 'Origem', Medicamento.ORIGENS),
               ('controlado', 'Controlado', [('True', 'Sim'), ('False', 'Não')]), ('ativo', 'Situação', ATIVO)]
    acoes_topo = [('cadastros:importar_cmed', 'bi-cloud-arrow-up', 'Importar tabela CMED'),
                  ('cadastros:interacao_list', 'bi-exclamation-diamond', 'Interações medicamentosas')]
    acoes_linha = [('cadastros:medicamento_bula', 'bi-file-earmark-text', 'Bula (Bulário ANVISA)')]


class ProcedimentoCrud(Crud):
    model, form_class = Procedimento, ProcedimentoForm
    nome, nome_plural, url, icone = 'Procedimento', 'Tabela de procedimentos', 'cadastros:procedimento', \
        'bi-clipboard2-pulse'
    descricao = 'Procedimentos SUS (SIGTAP), TUSS/CBHPM ou próprios da clínica.'
    colunas = [('codigo_formatado', 'Código'), ('nome', 'Procedimento'), ('origem', 'Origem'),
               ('complexidade', 'Complexidade'), ('valor_sus_total', 'Valor SUS', 'moeda'),
               ('valor_particular', 'Particular', 'moeda'), ('competencia', 'Competência'), ('ativo', 'Ativo')]
    busca = ['codigo', 'nome']
    filtros = [('origem', 'Origem', Procedimento.ORIGENS), ('ativo', 'Situação', ATIVO)]
    acoes_topo = [('cadastros:importar_procedimentos', 'bi-cloud-arrow-up', 'Importar SIGTAP / CSV')]


class CidCrud(Crud):
    model, form_class = Cid, CidForm
    global_ = True
    nome, nome_plural, url, icone = 'CID', 'Tabela CID-10 / CID-11', 'cadastros:cid', 'bi-journal-text'
    descricao = 'Classificação Internacional de Doenças (compartilhada entre todas as clínicas).'
    colunas = [('versao', 'Versão'), ('codigo', 'Código'), ('nome', 'Descrição'), ('sexo', 'Sexo'),
               ('ativo', 'Ativo')]
    busca = ['codigo', 'nome']
    filtros = [('versao', 'Versão', Cid.VERSOES)]
    acoes_topo = [('cadastros:importar_cid', 'bi-cloud-arrow-up', 'Importar CID-10 / CID-11')]


class TipoAtendimentoCrud(Crud):
    model, form_class = TipoAtendimento, TipoAtendimentoForm
    nome, nome_plural, url, icone = 'Tipo de atendimento', 'Tabela de preços', 'cadastros:tipo', 'bi-tags'
    descricao = 'Tipos de atendimento com duração e valores (particular, convênio e pacote).'
    colunas = [('nome', 'Atendimento'), ('especialidade', 'Especialidade'), ('procedimento__codigo', 'Proc.'),
               ('duracao_minutos', 'Duração (min)'), ('valor', 'Particular', 'moeda'),
               ('valor_convenio', 'Convênio', 'moeda'), ('valor_sessao_pacote', 'Sessão pacote', 'moeda'),
               ('permite_pacote', 'Pacote'), ('ativo', 'Ativo')]
    busca = ['nome']


@acesso('cadastros')
def paciente_ficha(request, pk):
    paciente = get_object_or_404(Paciente, pk=pk, clinica=request.clinica)
    from agenda.models import Agendamento, PacoteSessao
    from callcenter.models import ContatoPaciente
    from financeiro.models import Lancamento
    ctx = {
        'p': paciente,
        'agendamentos': Agendamento.objects.filter(paciente=paciente).select_related(
            'medico', 'tipo').order_by('-inicio')[:30],
        'pacotes': PacoteSessao.objects.filter(paciente=paciente).select_related('tipo').order_by('-data_compra'),
        'lancamentos': Lancamento.objects.filter(paciente=paciente).order_by('-vencimento')[:30]
        if tem_permissao(request, 'financeiro') else None,
        'contatos': ContatoPaciente.objects.filter(paciente=paciente).order_by('-data_prevista')[:20],
        'ver_prontuario': tem_permissao(request, 'prontuario'),
    }
    return render(request, 'cadastros/paciente_ficha.html', ctx)


# ------------------------------------------------------------------ importações
class ImportarCmedForm(FormSimples):
    arquivo = forms.FileField(label='Planilha CMED (.xlsx, .xls ou .csv)')
    aliquota = forms.ChoiceField(
        label='Alíquota de ICMS dos preços', initial='18',
        choices=[('SEM IMPOSTOS', 'PF sem impostos')] + [(a, f'{a}%') for a in
                                                         ('0', '12', '17', '17,5', '18', '19', '19,5', '20', '20,5',
                                                          '21', '22', '22,5', '23')],
        help_text='Use a alíquota interna de ICMS do seu estado (ex.: SP 18%, RJ 22%, MG 18%).')
    somente_comercializados = forms.BooleanField(label='Importar apenas produtos comercializados', required=False,
                                                 initial=True)
    atualizar = forms.BooleanField(label='Atualizar preços dos já importados', required=False, initial=True)


class ImportarProcForm(FormSimples):
    FONTES = [('sigtap', 'SUS - SIGTAP (ZIP da Tabela Unificada ou tb_procedimento.txt)'),
              ('tuss', 'TUSS / CBHPM (CSV: codigo;nome;valor)'), ('propria', 'Tabela própria (CSV: codigo;nome;valor)')]
    fonte = forms.ChoiceField(label='Tabela', choices=FONTES)
    arquivo = forms.FileField(label='Arquivo')


class ImportarCidForm(FormSimples):
    versao = forms.ChoiceField(label='Versão', choices=Cid.VERSOES)
    arquivo = forms.FileField(label='Arquivo', help_text='CID-10: CID10CSV.zip (DATASUS). CID-11: planilha '
                              '"Simple Tabulation" da OMS (.txt/.xlsx/.zip) ou CSV codigo;descricao.')


def _tela_importar(request, form, titulo, voltar, instrucoes):
    return render(request, 'cadastros/importar.html', {'form': form, 'titulo': titulo, 'voltar': voltar,
                                                       'instrucoes': instrucoes})


@acesso('cadastros', 'editar')
def importar_cmed(request):
    form = ImportarCmedForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            r = importacao.importar_cmed(request.clinica, d['arquivo'], d['aliquota'], d['somente_comercializados'],
                                         d['atualizar'])
            messages.success(request, f"CMED importada: {r['novos']} novo(s), {r['atualizados']} atualizado(s), "
                                      f"{r['ignorados']} não comercializado(s) ignorado(s).")
            return redirect('cadastros:medicamento_list')
        except importacao.ErroImportacao as e:
            messages.error(request, str(e))
    return _tela_importar(request, form, 'Importar tabela CMED / ANVISA', 'cadastros:medicamento_list', 'cmed')


@acesso('cadastros', 'editar')
def importar_procedimentos(request):
    form = ImportarProcForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        try:
            if d['fonte'] == 'sigtap':
                r = importacao.importar_sigtap(request.clinica, d['arquivo'])
                extra = f", {r['inativados']} inativado(s) (fora da competência)"
            else:
                r = importacao.importar_procedimentos_csv(request.clinica, d['arquivo'], d['fonte'])
                extra = ''
            messages.success(request, f"Procedimentos importados: {r['novos']} novo(s), "
                                      f"{r['atualizados']} atualizado(s){extra}.")
            return redirect('cadastros:procedimento_list')
        except importacao.ErroImportacao as e:
            messages.error(request, str(e))
    return _tela_importar(request, form, 'Importar tabela de procedimentos', 'cadastros:procedimento_list',
                          'sigtap')


@acesso('cadastros', 'editar')
def importar_cid(request):
    if not (request.user.is_superuser or tem_permissao(request, 'administrativo', 'editar')):
        raise PermissionDenied
    form = ImportarCidForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        try:
            r = importacao.importar_cid(form.cleaned_data['arquivo'], form.cleaned_data['versao'])
            messages.success(request, f"CID-{form.cleaned_data['versao']} importado: {r['novos']} novo(s), {r['atualizados']} atualizado(s).")
            return redirect('cadastros:cid_list')
        except importacao.ErroImportacao as e:
            messages.error(request, str(e))
    return _tela_importar(request, form, 'Importar CID-10 / CID-11', 'cadastros:cid_list', 'cid')


# ------------------------------------------------------------------ APIs de busca (autocomplete)
def _termos(q):
    return [t for t in q.split() if t][:5]


@acesso(None)
def api_medicamentos(request):
    q = request.GET.get('q', '').strip()
    qs = Medicamento.objects.filter(clinica=request.clinica, ativo=True)
    for t in _termos(q):
        qs = qs.filter(Q(nome__icontains=t) | Q(principio_ativo__icontains=t) | Q(apresentacao__icontains=t) |
                       Q(ean=t))
    return JsonResponse([{
        'id': m.pk, 'texto': str(m), 'valor': str(m), 'posologia': m.posologia_padrao,
        'extra': ' · '.join(x for x in [m.principio_ativo[:60], m.laboratorio[:40],
                                        f'PMC {moeda(m.preco_maximo_consumidor)}' if m.preco_maximo_consumidor else '',
                                        'CONTROLADO' if m.controlado else ''] if x)}
        for m in qs.order_by('nome')[:20]], safe=False)


@acesso(None)
def api_procedimentos(request):
    q = request.GET.get('q', '').strip()
    qs = Procedimento.objects.filter(clinica=request.clinica, ativo=True)
    digitos = q.replace('.', '').replace('-', '')
    if digitos.isdigit():
        qs = qs.filter(codigo__startswith=digitos)
    else:
        for t in _termos(q):
            qs = qs.filter(nome__icontains=t)
    return JsonResponse([{'id': p.pk, 'texto': str(p), 'valor': p.codigo,
                          'extra': f'{p.get_origem_display()} · SUS {moeda(p.valor_sus_total)}'}
                         for p in qs[:20]], safe=False)


@acesso(None)
def api_cid(request):
    q = request.GET.get('q', '').strip()
    qs = Cid.objects.filter(ativo=True)
    if request.GET.get('versao') in ('10', '11'):
        qs = qs.filter(versao=request.GET['versao'])
    if len(q) <= 7 and ' ' not in q and any(ch.isdigit() for ch in q):
        qs = qs.filter(codigo__istartswith=q.upper())
    else:
        for t in _termos(q):
            qs = qs.filter(nome__icontains=t)
    return JsonResponse([{'id': c.pk, 'texto': str(c), 'valor': c.codigo} for c in qs[:20]], safe=False)


class InteracaoCrud(Crud):
    model, form_class = InteracaoMedicamentosa, InteracaoForm
    global_ = True
    nome, nome_plural, url, icone = 'Interação', 'Interações medicamentosas', 'cadastros:interacao', \
        'bi-exclamation-diamond'
    descricao = ('Base de apoio à decisão usada na prescrição (não substitui bulas e compêndios oficiais). '
                 'Termos separados por vírgula, comparados com o princípio ativo e o nome dos medicamentos.')
    colunas = [('substancia_a', 'Substância A'), ('substancia_b', 'Substância B'), ('gravidade', 'Gravidade'),
               ('efeito', 'Efeito'), ('ativo', 'Ativo')]
    busca = ['substancia_a', 'substancia_b', 'efeito']
    filtros = [('gravidade', 'Gravidade', InteracaoMedicamentosa.GRAVIDADE)]
    acoes_topo = [('cadastros:interacao_importar', 'bi-cloud-arrow-up', 'Importar / carregar base')]


class ImportarInteracaoForm(FormSimples):
    carregar_base = forms.BooleanField(label='Carregar a base inicial do sistema (interações mais relevantes)',
                                       required=False, initial=True)
    arquivo = forms.FileField(label='CSV adicional (opcional)', required=False,
                              help_text='Colunas: substancia_a;substancia_b;gravidade;efeito;conduta '
                                        '(gravidade: contraindicada, grave, moderada, leve).')


@acesso('cadastros', 'editar')
def interacao_importar(request):
    form = ImportarInteracaoForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        from . import interacoes_base
        n = interacoes_base.carregar() if form.cleaned_data['carregar_base'] else 0
        if form.cleaned_data['arquivo']:
            linhas = importacao.ler_linhas(form.cleaned_data['arquivo'])
            next(linhas, None)
            gravs = dict(InteracaoMedicamentosa.GRAVIDADE)
            for row in linhas:
                if len(row) >= 4 and row[0] and row[1]:
                    g = importacao.norm(row[2]).lower()
                    InteracaoMedicamentosa.objects.update_or_create(
                        substancia_a=str(row[0]).strip()[:600], substancia_b=str(row[1]).strip()[:600],
                        defaults={'gravidade': g if g in gravs else 'moderada', 'efeito': str(row[3]).strip(),
                                  'conduta': str(row[4]).strip() if len(row) > 4 else '', 'fonte': 'Importação CSV'})
                    n += 1
        messages.success(request, f'{n} interação(ões) carregada(s)/atualizada(s).')
        return redirect('cadastros:interacao_list')
    return _tela_importar(request, form, 'Interações medicamentosas', 'cadastros:interacao_list', 'interacoes')


@acesso('cadastros')
def medicamento_bula(request, pk):
    m = get_object_or_404(Medicamento, pk=pk, clinica=request.clinica)
    return redirect(m.bula_url)


@acesso(None)
def api_verificar_prescricao(request):
    """Alergias + interações entre os itens da prescrição e os medicamentos em uso do paciente."""
    from .interacoes import itens_em_uso, verificar, verificar_alergias
    paciente = Paciente.objects.filter(clinica=request.clinica, pk=request.GET.get('paciente') or 0).first()
    itens = []
    for mid in request.GET.getlist('med'):
        m = Medicamento.objects.filter(clinica=request.clinica, pk=mid).first()
        if m:
            itens.append((m.nome, f'{m.nome} {m.principio_ativo}'))
    for txt in request.GET.getlist('txt'):
        if txt.strip():
            itens.append((txt.strip(), txt))
    alergias, conflitos = verificar_alergias(paciente, itens) if paciente else ('', [])
    todos = itens + (itens_em_uso(paciente) if paciente else [])
    interacoes = [a for a in verificar(todos) if not (a['a'].endswith('(uso contínuo)') and
                                                       a['b'].endswith('(uso contínuo)'))]
    return JsonResponse({'alergias': alergias, 'conflitos_alergia': conflitos, 'interacoes': interacoes})


@acesso(None)
def api_pacientes(request):
    q = request.GET.get('q', '').strip()
    qs = Paciente.objects.filter(clinica=request.clinica, ativo=True)
    for t in _termos(q):
        qs = qs.filter(Q(nome__icontains=t) | Q(cpf__icontains=t) | Q(celular__icontains=t))
    return JsonResponse([{'id': p.pk, 'texto': p.nome, 'valor': p.nome,
                          'extra': ' · '.join(x for x in [p.cpf, p.celular] if x)} for p in qs[:20]], safe=False)
