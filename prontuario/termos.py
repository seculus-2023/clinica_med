"""Termos de consentimento assinados pelo paciente na tela."""
import base64
import hashlib

from django import forms
from django.contrib import messages
from django.core.files.base import ContentFile
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from contas.crud import ClinicaModelForm, Crud, FormSimples
from contas.permissoes import acesso, medico_do_usuario

from .models import Atendimento, ModeloTermo, TermoAssinado
from .views import _paciente, registrar

TERMOS_PADRAO = {
    'Consentimento para procedimento': (
        'Eu, {paciente}, CPF {cpf}, declaro que fui informado(a) pelo(a) profissional {medico} ({registro}), de forma '
        'clara e compreensível, sobre o procedimento {procedimento}: sua indicação, benefícios esperados, riscos, '
        'possíveis complicações, cuidados necessários e alternativas de tratamento. Tive a oportunidade de fazer '
        'perguntas, que foram respondidas satisfatoriamente.\n\nAutorizo a realização do procedimento e estou ciente '
        'de que posso revogar este consentimento a qualquer momento antes de sua realização.\n\n{clinica}, {data}.'),
    'Autorização de uso de imagem': (
        'Eu, {paciente}, CPF {cpf}, autorizo a {clinica} a registrar fotografias/vídeos do meu tratamento para fins '
        'de documentação clínica no prontuário. O uso para fins científicos ou de divulgação somente ocorrerá com '
        'minha identidade preservada e mediante nova autorização específica.\n\n{data}.'),
    'Consentimento LGPD - tratamento de dados': (
        'Eu, {paciente}, CPF {cpf}, autorizo a {clinica} a tratar meus dados pessoais e dados pessoais sensíveis '
        'de saúde para as finalidades de atendimento, agendamento, comunicação (WhatsApp, SMS e e-mail), faturamento '
        'junto a convênios e cumprimento de obrigações legais, nos termos da Lei 13.709/2018 (LGPD). Estou ciente '
        'de que posso solicitar acesso, correção, portabilidade e a revogação deste consentimento.\n\n{data}.'),
}


def criar_termos_padrao(clinica):
    n = 0
    for nome, texto in TERMOS_PADRAO.items():
        n += ModeloTermo.objects.get_or_create(clinica=clinica, nome=nome, defaults={'texto': texto})[1]
    return n


class ModeloTermoForm(ClinicaModelForm):
    class Meta:
        model = ModeloTermo
        exclude = []
        widgets = {'texto': forms.Textarea(attrs={'rows': 12})}


class ModeloTermoCrud(Crud):
    model, form_class = ModeloTermo, ModeloTermoForm
    modulo = 'prontuario'
    nome, nome_plural, url, icone = 'Modelo de termo', 'Modelos de termos de consentimento', 'prontuario:termo_modelo', \
        'bi-file-earmark-check'
    descricao = 'Variáveis: {paciente} {cpf} {data} {medico} {registro} {clinica} {procedimento}'
    colunas = [('nome', 'Termo'), ('ativo', 'Ativo')]
    busca = ['nome', 'texto']


class TermoForm(FormSimples):
    modelo = forms.ModelChoiceField(label='Modelo', queryset=ModeloTermo.objects.none(), required=False)
    titulo = forms.CharField(label='Título', max_length=150)
    procedimento = forms.CharField(label='Procedimento (para a variável {procedimento})', max_length=200, required=False)
    texto = forms.CharField(label='Texto do termo', widget=forms.Textarea(attrs={'rows': 12}))
    assinante_nome = forms.CharField(label='Nome de quem assina', max_length=150)
    assinante_documento = forms.CharField(label='CPF/RG de quem assina', max_length=30, required=False)
    assinante_relacao = forms.ChoiceField(label='Quem assina', choices=[(x, x) for x in (
        'Próprio paciente', 'Responsável legal', 'Pai/mãe', 'Cônjuge', 'Curador', 'Outro')])
    assinatura = forms.CharField(widget=forms.HiddenInput, error_messages={'required': 'O paciente precisa assinar no quadro.'})

    def clean_assinatura(self):
        v = self.cleaned_data['assinatura']
        if not v.startswith('data:image/png;base64,') or len(v) < 200 or len(v) > 3_000_000:
            raise forms.ValidationError('Assinatura inválida: peça para o paciente assinar no quadro.')
        return v


def preencher(texto, paciente, medico, clinica, procedimento=''):
    vals = {'{paciente}': paciente.nome, '{cpf}': paciente.cpf or '___________', '{data}': timezone.localtime().strftime('%d/%m/%Y'),
            '{medico}': medico.nome if medico else '', '{registro}': medico.registro_completo if medico else '',
            '{clinica}': clinica.nome, '{procedimento}': procedimento or '__________________'}
    for k, v in vals.items():
        texto = texto.replace(k, v)
    return texto


@acesso('prontuario', 'editar')
def termo_novo(request, pk):
    from documentos.models import gerar_codigo
    p = _paciente(request, pk)
    if not ModeloTermo.objects.filter(clinica=request.clinica).exists():
        criar_termos_padrao(request.clinica)
    medico = medico_do_usuario(request)
    modelo = ModeloTermo.objects.filter(clinica=request.clinica, pk=request.GET.get('modelo') or 0).first()
    inicial = {'assinante_nome': p.nome, 'assinante_documento': p.cpf}
    if modelo:
        inicial.update({'modelo': modelo.pk, 'titulo': modelo.nome,
                        'texto': preencher(modelo.texto, p, medico, request.clinica, request.GET.get('procedimento', ''))})
    form = TermoForm(request.POST or None, initial=inicial)
    form.fields['modelo'].queryset = ModeloTermo.objects.filter(clinica=request.clinica, ativo=True)
    form.fields['modelo'].widget.attrs['class'] = 'form-select'
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        png = base64.b64decode(d['assinatura'].split(',', 1)[1])
        agora = timezone.now()
        texto = d['texto'].replace('{procedimento}', d['procedimento'] or '__________________')
        t = TermoAssinado(
            clinica=request.clinica, paciente=p, medico=medico, titulo=d['titulo'], texto=texto,
            atendimento=Atendimento.objects.filter(pk=request.GET.get('atendimento') or 0, paciente=p).first(),
            assinante_nome=d['assinante_nome'], assinante_documento=d['assinante_documento'],
            assinante_relacao=d['assinante_relacao'], assinado_em=agora, usuario=request.user,
            ip=(request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR') or None),
            codigo_verificacao=gerar_codigo(),
            sha256=hashlib.sha256(texto.encode() + png + agora.isoformat().encode()).hexdigest())
        t.assinatura.save(f'termo_{p.pk}_{agora:%Y%m%d%H%M%S}.png', ContentFile(png), save=False)
        t.save()
        registrar(request, p, f'Termo assinado: {t.titulo}')
        messages.success(request, 'Termo assinado e guardado no prontuário.')
        return redirect('prontuario:termo', t.pk)
    return render(request, 'prontuario/termo_form.html', {'form': form, 'p': p, 'modelos': form.fields['modelo'].queryset,
                                                          'modelo': modelo})


@acesso('prontuario')
def termo(request, pk):
    from documentos.models import url_verificacao
    t = get_object_or_404(TermoAssinado.objects.select_related('paciente', 'medico', 'clinica'), pk=pk,
                          clinica=request.clinica)
    _paciente(request, t.paciente_id)
    return render(request, 'prontuario/termo_imprimir.html', {'t': t, 'c': t.clinica,
                                                              'url_verificacao': url_verificacao(t.codigo_verificacao)})


@acesso('prontuario')
def termo_assinatura(request, pk):
    t = get_object_or_404(TermoAssinado, pk=pk, clinica=request.clinica)
    _paciente(request, t.paciente_id)
    resp = FileResponse(t.assinatura.open('rb'), content_type='image/png')
    resp['Cache-Control'] = 'private, no-store'
    return resp
