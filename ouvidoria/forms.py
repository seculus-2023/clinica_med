from django import forms

from agenda.publico import TEXTO_LGPD
from cadastros.models import Medico, Paciente
from contas.crud import Autocomplete, ClinicaModelForm, FormSimples

from .models import ConfigOuvidoria, Manifestacao, Setor
from .services import usuarios_da_clinica


def _digitos(s):
    return ''.join(c for c in str(s or '') if c.isdigit())


class ManifestacaoForm(ClinicaModelForm):
    """Registro feito pela equipe (presencial, telefone, e-mail...)."""

    class Meta:
        model = Manifestacao
        fields = ['tipo', 'canal', 'prioridade', 'assunto', 'descricao', 'data_ocorrido', 'setor', 'medico',
                  'paciente', 'anonima', 'sigilosa', 'nome', 'telefone', 'email', 'relacao', 'aceita_contato']
        widgets = {'descricao': forms.Textarea(attrs={'rows': 5}),
                   'paciente': Autocomplete('cadastros:api_pacientes', Paciente)}
        help_texts = {'paciente': 'Opcional: vincula ao cadastro e preenche nome e contato.'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['canal'].choices = [c for c in Manifestacao.CANAIS if c[0] not in ('site', 'app', 'nps')]

    def clean(self):
        d = super().clean()
        if not d.get('anonima') and not (d.get('nome') or d.get('paciente')):
            self.add_error('nome', 'Informe o nome, vincule um paciente ou marque como anônima.')
        return d


class ManifestacaoEditarForm(ClinicaModelForm):
    """Classificação feita pela ouvidoria depois do registro."""

    class Meta:
        model = Manifestacao
        fields = ['tipo', 'prioridade', 'assunto', 'data_ocorrido', 'setor', 'medico', 'sigilosa']


class PublicoForm(FormSimples):
    tipo = forms.ChoiceField(label='O que você deseja registrar?', choices=Manifestacao.TIPOS)
    assunto = forms.CharField(label='Assunto', max_length=150)
    descricao = forms.CharField(label='Conte o que aconteceu', widget=forms.Textarea(attrs={'rows': 6}),
                                max_length=5000,
                                help_text='Se possível, informe data, horário, local e pessoas envolvidas.')
    data_ocorrido = forms.DateField(label='Quando aconteceu?', required=False)
    setor = forms.ModelChoiceField(label='Setor relacionado', queryset=Setor.objects.none(), required=False,
                                   empty_label='Não sei / não se aplica')
    medico = forms.ModelChoiceField(label='Profissional relacionado', queryset=Medico.objects.none(),
                                    required=False, empty_label='Nenhum / não sei')
    anonima = forms.BooleanField(label='Quero me manter anônimo(a)', required=False,
                                 help_text='Sem identificação não conseguimos contatar você. Guarde o protocolo e a '
                                           'chave para acompanhar a resposta.')
    nome = forms.CharField(label='Seu nome', max_length=150, required=False)
    telefone = forms.CharField(label='Celular / WhatsApp', max_length=20, required=False)
    email = forms.EmailField(label='E-mail', required=False)
    relacao = forms.ChoiceField(label='Você é', choices=[('', '---------')] + Manifestacao.RELACOES, required=False)
    sigilosa = forms.BooleanField(label='Peço sigilo da minha identidade', required=False,
                                  help_text='Seu nome fica restrito à equipe da ouvidoria.')
    lgpd = forms.BooleanField(label=TEXTO_LGPD)
    site = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot anti-robô

    def __init__(self, *args, clinica=None, config=None, paciente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.paciente = paciente
        self.fields['setor'].queryset = Setor.objects.filter(clinica=clinica, ativo=True, publico=True)
        self.fields['medico'].queryset = Medico.objects.filter(clinica=clinica, ativo=True)
        if paciente is not None:   # app do paciente: identidade já conhecida
            for campo in ('nome', 'telefone', 'email', 'relacao', 'lgpd'):
                del self.fields[campo]
        if paciente is not None or (config and not config.permitir_anonimo):
            del self.fields['anonima']

    def clean(self):
        d = super().clean()
        if self.paciente is None and not d.get('anonima'):
            if not d.get('nome'):
                self.add_error('nome', 'Informe seu nome ou marque a opção anônima.')
            if len(_digitos(d.get('telefone'))) < 10 and not d.get('email'):
                self.add_error('telefone', 'Informe um celular com DDD ou um e-mail para receber a resposta.')
        return d


class ConsultarForm(FormSimples):
    protocolo = forms.CharField(label='Protocolo', max_length=12, widget=forms.TextInput(attrs={'placeholder': '2026-00001'}))
    chave = forms.CharField(label='Chave de acesso', max_length=12, widget=forms.TextInput(
        attrs={'placeholder': 'ABCD-EFGH', 'autocomplete': 'off', 'autocapitalize': 'characters'}))


class MensagemPublicaForm(FormSimples):
    texto = forms.CharField(label='Enviar complemento ou réplica', max_length=3000,
                            widget=forms.Textarea(attrs={'rows': 3}))


class AvaliacaoForm(FormSimples):
    resolvida = forms.TypedChoiceField(label='Sua demanda foi resolvida?', coerce=lambda v: v == '1',
                                       choices=[('1', 'Sim'), ('0', 'Não')], widget=forms.RadioSelect)
    nota = forms.TypedChoiceField(label='Qual sua satisfação com a resposta? (1 = muito insatisfeito, 5 = muito '
                                        'satisfeito)', coerce=int, choices=[(i, str(i)) for i in range(1, 6)],
                                  widget=forms.RadioSelect)
    comentario = forms.CharField(label='Comentário (opcional)', required=False, max_length=1000,
                                 widget=forms.Textarea(attrs={'rows': 2}))


class TextoForm(FormSimples):
    texto = forms.CharField(label='Texto', widget=forms.Textarea(attrs={'rows': 4}), max_length=5000)


class RespostaForm(FormSimples):
    texto = forms.CharField(label='Resposta ao manifestante', widget=forms.Textarea(attrs={'rows': 6}),
                            max_length=5000, help_text='É exibida ao manifestante e enviada por WhatsApp/e-mail '
                                                       'quando há contato.')
    concluir = forms.BooleanField(label='Concluir a manifestação junto com a resposta', required=False)
    conclusao = forms.ChoiceField(label='Conclusão', choices=[('', '---------')] + Manifestacao.CONCLUSOES,
                                  required=False)

    def clean(self):
        d = super().clean()
        if d.get('concluir') and not d.get('conclusao'):
            self.add_error('conclusao', 'Informe a conclusão.')
        return d


class EncaminharForm(FormSimples):
    setor = forms.ModelChoiceField(label='Setor', queryset=Setor.objects.none(), required=False)
    destino = forms.ModelChoiceField(label='Encaminhar para', queryset=None, required=False,
                                     help_text='Vazio = responsável do setor.')
    texto = forms.CharField(label='Orientação', widget=forms.Textarea(attrs={'rows': 3}), required=False,
                            max_length=2000)

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['setor'].queryset = Setor.objects.filter(clinica=clinica, ativo=True)
        self.fields['destino'].queryset = usuarios_da_clinica(clinica)


class ProrrogarForm(FormSimples):
    dias = forms.IntegerField(label='Dias a mais', min_value=1)
    texto = forms.CharField(label='Motivo (informado ao manifestante)', max_length=500)


class ConcluirForm(FormSimples):
    conclusao = forms.ChoiceField(label='Conclusão', choices=Manifestacao.CONCLUSOES)
    texto = forms.CharField(label='Observação (visível ao manifestante)', required=False, max_length=2000,
                            widget=forms.Textarea(attrs={'rows': 2}))


class MotivoForm(FormSimples):
    texto = forms.CharField(label='Motivo', max_length=500)


class ConfigForm(ClinicaModelForm):
    class Meta:
        model = ConfigOuvidoria
        fields = ['formulario_publico', 'permitir_anonimo', 'prazo_dias', 'prorrogacao_dias', 'ouvidor',
                  'email_alerta', 'abrir_por_nps', 'concluir_sem_retorno_dias', 'apresentacao']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['ouvidor'].queryset = usuarios_da_clinica(self.clinica)

    def clean_prazo_dias(self):
        v = self.cleaned_data['prazo_dias']
        if not 1 <= v <= 60:
            raise forms.ValidationError('Use um prazo entre 1 e 60 dias.')
        return v


class SetorForm(ClinicaModelForm):
    class Meta:
        model = Setor
        fields = ['nome', 'responsavel', 'publico', 'ativo']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsavel'].queryset = usuarios_da_clinica(self.clinica)
