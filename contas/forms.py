from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .crud import ClinicaModelForm, estilizar_campos
from .models import MODULOS, NIVEIS, Clinica, Lembrete, Perfil

Usuario = get_user_model()


class LoginForm(AuthenticationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Usuário',
                                                     'autocomplete': 'username'})
        self.fields['password'].widget.attrs.update({'class': 'form-control', 'placeholder': 'Senha',
                                                     'autocomplete': 'current-password'})


class ClinicaForm(forms.ModelForm):
    class Meta:
        model = Clinica
        fields = ['nome', 'razao_social', 'cnpj', 'telefone', 'whatsapp', 'email', 'endereco', 'cidade', 'uf',
                  'fuso_horario', 'logo', 'ativa']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        estilizar_campos(self)


class ConfiguracaoClinicaForm(forms.ModelForm):
    class Meta:
        model = Clinica
        fields = ['nome', 'razao_social', 'cnpj', 'telefone', 'whatsapp', 'email', 'endereco', 'cidade', 'uf',
                  'logo', 'fuso_horario', 'lembrete_horas_antes', 'callcenter_dias_apos', 'notificar_whatsapp', 'notificar_email',
                  'whatsapp_provedor', 'whatsapp_api_url', 'whatsapp_instancia', 'whatsapp_token',
                  'email_remetente', 'smtp_host', 'smtp_porta', 'smtp_usuario', 'smtp_senha', 'smtp_tls',
                  'notificar_sms', 'sms_provedor', 'sms_conta', 'sms_token', 'sms_remetente', 'sms_url',
                  'enviar_nps', 'enviar_aniversario', 'agendamento_online',
                  'online_antecedencia_horas', 'online_dias', 'telemedicina_url', 'google_avaliacao_url',
                  'taxa_credito', 'taxa_debito',
                  'msg_agendamento', 'msg_lembrete', 'msg_cancelamento', 'msg_pos_consulta', 'msg_nps',
                  'msg_aniversario']
        widgets = {'whatsapp_token': forms.PasswordInput(render_value=True),
                   'smtp_senha': forms.PasswordInput(render_value=True),
                   'sms_token': forms.PasswordInput(render_value=True)}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        estilizar_campos(self)

    def _grupo(self, inicio, fim):
        nomes = self.Meta.fields
        return [self[n] for n in nomes[nomes.index(inicio):nomes.index(fim) + 1]]

    def grupo_dados(self):
        return self._grupo('nome', 'fuso_horario')

    def grupo_notificacoes(self):
        return self._grupo('lembrete_horas_antes', 'email_remetente') + self._grupo('enviar_nps', 'enviar_aniversario')

    def grupo_smtp(self):
        return self._grupo('smtp_host', 'smtp_tls')

    def grupo_sms(self):
        return self._grupo('notificar_sms', 'sms_url')

    def grupo_online(self):
        return self._grupo('agendamento_online', 'taxa_debito')

    def grupo_mensagens(self):
        return self._grupo('msg_agendamento', 'msg_aniversario')


class PerfilForm(ClinicaModelForm):
    class Meta:
        model = Perfil
        fields = ['nome', 'descricao', 'apenas_propria_agenda']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for mod, rotulo in MODULOS:
            self.fields[f'perm_{mod}'] = forms.ChoiceField(
                label=rotulo, choices=NIVEIS, initial=self.instance.nivel(mod) if self.instance.pk else 'ver',
                widget=forms.Select(attrs={'class': 'form-select form-select-sm'}))

    def campos_permissao(self):
        return [self[f'perm_{m}'] for m, _ in MODULOS]

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.permissoes = {m: self.cleaned_data[f'perm_{m}'] for m, _ in MODULOS}
        if commit:
            obj.save()
        return obj


class UsuarioClinicaForm(forms.Form):
    username = forms.CharField(label='Usuário (login)', max_length=150)
    first_name = forms.CharField(label='Nome', max_length=150)
    last_name = forms.CharField(label='Sobrenome', max_length=150, required=False)
    email = forms.EmailField(label='E-mail', required=False)
    telefone = forms.CharField(label='Celular / WhatsApp', max_length=20, required=False)
    perfil = forms.ModelChoiceField(label='Perfil de acesso', queryset=Perfil.objects.none())
    senha = forms.CharField(label='Senha', widget=forms.PasswordInput, required=False,
                            help_text='Obrigatória para novo usuário. Deixe vazio para manter a atual.')
    ativo = forms.BooleanField(label='Acesso ativo nesta clínica', required=False, initial=True)

    def __init__(self, *args, clinica=None, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinica = clinica
        self.usuario = usuario
        self.fields['perfil'].queryset = Perfil.objects.filter(clinica=clinica)
        estilizar_campos(self)

    def clean_username(self):
        u = self.cleaned_data['username'].strip()
        qs = Usuario.objects.filter(username__iexact=u)
        if self.usuario:
            qs = qs.exclude(pk=self.usuario.pk)
        if qs.exists():
            raise forms.ValidationError('Já existe um usuário com este login.')
        return u

    def clean(self):
        dados = super().clean()
        if not self.usuario and not dados.get('senha'):
            self.add_error('senha', 'Informe a senha do novo usuário.')
        if dados.get('senha') and len(dados['senha']) < 6:
            self.add_error('senha', 'A senha deve ter ao menos 6 caracteres.')
        return dados


class LembreteForm(ClinicaModelForm):
    class Meta:
        model = Lembrete
        fields = ['titulo', 'mensagem', 'data_hora', 'usuario', 'enviar_email', 'concluido']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['usuario'].queryset = Usuario.objects.filter(
            vinculos__clinica=self.clinica, vinculos__ativo=True).distinct()
        self.fields['usuario'].empty_label = 'Todos os usuários da clínica'
