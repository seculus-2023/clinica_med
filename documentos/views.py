from django import forms
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from agenda.models import Agendamento
from cadastros.models import Medicamento, Medico
from contas.crud import Autocomplete, ClinicaModelForm, Crud, estilizar_campos
from contas.permissoes import acesso, medico_restrito

from .models import PLACEHOLDERS, Documento, ItemPrescricao, ModeloDocumento


class DocumentoForm(ClinicaModelForm):
    modelo = forms.ModelChoiceField(label='Usar modelo', queryset=ModeloDocumento.objects.none(), required=False)

    class Meta:
        model = Documento
        fields = ['tipo', 'paciente', 'medico', 'data', 'titulo', 'cid', 'dias', 'conteudo']
        widgets = {'conteudo': forms.Textarea(attrs={'rows': 10}),
                   'cid': Autocomplete('cadastros:api_cid', modo='texto')}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['modelo'].queryset = ModeloDocumento.objects.filter(clinica=self.clinica, ativo=True)
        self.fields['modelo'].widget.attrs['class'] = 'form-select'
        self.fields['conteudo'].help_text = 'Variáveis aceitas: ' + ' '.join(PLACEHOLDERS)


class ItemForm(forms.ModelForm):
    class Meta:
        model = ItemPrescricao
        fields = ['medicamento', 'descricao', 'quantidade', 'posologia']
        widgets = {'medicamento': Autocomplete('cadastros:api_medicamentos', Medicamento)}

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['medicamento'].queryset = Medicamento.objects.filter(clinica=clinica)
        self.fields['descricao'].label = 'Ou texto livre'
        estilizar_campos(self)


ItensFormSet = forms.inlineformset_factory(Documento, ItemPrescricao, form=ItemForm, extra=3, can_delete=True)


class ModeloForm(ClinicaModelForm):
    class Meta:
        model = ModeloDocumento
        exclude = []
        widgets = {'conteudo': forms.Textarea(attrs={'rows': 10})}


class DocumentoCrud(Crud):
    model, form_class = Documento, DocumentoForm
    modulo = 'documentos'
    nome, nome_plural, url, icone = 'Documento', 'Prescrições e documentos', 'documentos:documento', \
        'bi-file-earmark-medical'
    colunas = [('data', 'Data'), ('tipo', 'Tipo'), ('paciente', 'Paciente'), ('medico', 'Profissional'),
               ('titulo', 'Título')]
    busca = ['paciente__nome', 'titulo', 'conteudo']
    from .models import TIPOS as _T
    filtros = [('tipo', 'Tipo', _T)]
    acoes_linha = [('documentos:imprimir', 'bi-printer', 'Imprimir')]

    @classmethod
    def queryset(cls, request):
        qs = Documento.objects.filter(clinica=request.clinica).select_related('paciente', 'medico')
        med = medico_restrito(request)
        return qs.filter(medico=med) if med else qs


class ModeloCrud(Crud):
    model, form_class = ModeloDocumento, ModeloForm
    modulo = 'documentos'
    nome, nome_plural, url, icone = 'Modelo', 'Modelos de documentos', 'documentos:modelo', 'bi-file-text'
    colunas = [('nome', 'Nome'), ('tipo', 'Tipo'), ('ativo', 'Ativo')]
    busca = ['nome', 'conteudo']


@acesso('documentos', 'editar')
def documento_form(request, pk=None):
    doc = get_object_or_404(DocumentoCrud.queryset(request), pk=pk) if pk else None
    inicial = {}
    ag = None
    if not doc:
        inicial = {k: v for k, v in request.GET.items() if k in ('tipo', 'paciente', 'medico')}
        if request.GET.get('atendimento'):
            from prontuario.models import Atendimento
            atend = Atendimento.objects.filter(pk=request.GET['atendimento'], clinica=request.clinica).first()
            if atend:
                ag = atend.agendamento
                inicial.update({'paciente': atend.paciente_id, 'medico': atend.medico_id,
                                'cid': atend.cid_principal.codigo if atend.cid_principal else ''})
        elif request.GET.get('agendamento'):
            ag = Agendamento.objects.filter(pk=request.GET['agendamento'], clinica=request.clinica).first()
            if ag:
                inicial.update({'paciente': ag.paciente_id, 'medico': ag.medico_id})
        med = medico_restrito(request) or Medico.objects.filter(clinica=request.clinica,
                                                                usuario=request.user).first()
        if med:
            inicial.setdefault('medico', med.pk)
    form = DocumentoForm(request.POST or None, instance=doc, initial=inicial, clinica=request.clinica)
    itens = ItensFormSet(request.POST or None, instance=doc or Documento(), form_kwargs={'clinica': request.clinica})
    if request.method == 'POST' and form.is_valid() and itens.is_valid():
        with transaction.atomic():
            obj = form.save(commit=False)
            if not obj.pk:
                obj.clinica = request.clinica
                obj.agendamento = ag
                if request.GET.get('atendimento'):
                    from prontuario.models import Atendimento
                    obj.atendimento = Atendimento.objects.filter(
                        pk=request.GET['atendimento'], clinica=request.clinica, paciente=obj.paciente).first()
            obj.conteudo = obj.preencher(obj.conteudo)
            obj.save()
            itens.instance = obj
            for i, item in enumerate(itens.save(commit=False)):
                if item.medicamento_id or item.descricao:
                    item.ordem = i
                    item.save()
            for item in itens.deleted_objects:
                item.delete()
        messages.success(request, 'Documento salvo.')
        _avisos_seguranca(request, obj)
        if request.POST.get('imprimir'):
            return redirect('documentos:imprimir', obj.pk)
        return redirect('documentos:documento_list')
    return render(request, 'documentos/form.html', {'form': form, 'itens': itens, 'obj': doc,
                                                    'placeholders': PLACEHOLDERS})


@acesso('documentos')
def imprimir(request, pk):
    doc = get_object_or_404(DocumentoCrud.queryset(request).select_related('clinica'), pk=pk)
    return render(request, 'documentos/imprimir.html', {'doc': doc, 'c': doc.clinica})


@acesso('documentos')
def api_alergias(request, pk):
    from cadastros.models import Paciente
    from prontuario.models import HistoricoClinico
    p = get_object_or_404(Paciente, pk=pk, clinica=request.clinica)
    h = HistoricoClinico.objects.filter(paciente=p).first()
    textos = [t for t in {p.alergias.strip(), (h.alergias.strip() if h else '')} if t]
    return JsonResponse({'alergias': '; '.join(textos)})


@acesso('documentos')
def api_modelo(request, pk):
    m = get_object_or_404(ModeloDocumento, pk=pk, clinica=request.clinica)
    return JsonResponse({'tipo': m.tipo, 'conteudo': m.conteudo, 'titulo': m.nome})



def _avisos_seguranca(request, doc):
    """Repete, após salvar, os alertas de alergia e interação (registro de que o prescritor foi avisado)."""
    from cadastros.interacoes import itens_em_uso, verificar, verificar_alergias
    itens = [(i.nome, f'{i.nome} {i.medicamento.principio_ativo if i.medicamento else ""}') for i in doc.itens.all()]
    if not itens:
        return
    _, conflitos = verificar_alergias(doc.paciente, itens)
    for c in conflitos:
        messages.error(request, f'ALERGIA: {c["item"]} pode conflitar com a alergia registrada ({c["alergia"]}).')
    for a in verificar(itens + itens_em_uso(doc.paciente)):
        if not (a['a'].endswith('(uso contínuo)') and a['b'].endswith('(uso contínuo)')):
            messages.warning(request, f'Interação {a["gravidade_txt"].upper()}: {a["a"]} × {a["b"]} — {a["efeito"]}')
