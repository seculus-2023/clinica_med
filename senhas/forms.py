from django import forms

from contas.crud import ClinicaModelForm
from contas.models import Usuario

from .models import ConfigPainel, PontoAtendimento, ServicoSenha


class ServicoForm(ClinicaModelForm):
    class Meta:
        model = ServicoSenha
        fields = ['nome', 'prefixo', 'ordem', 'ativo']

    def clean_prefixo(self):
        prefixo = self.cleaned_data['prefixo'].upper()
        if not ('A' <= prefixo <= 'Z') or prefixo == 'P':
            raise forms.ValidationError('Use uma letra de A a Z, exceto P (reservada para preferencial).')
        repetido = ServicoSenha.objects.filter(clinica=self.clinica, prefixo=prefixo).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError('Já existe um serviço com esta letra.')
        return prefixo


class PontoForm(ClinicaModelForm):
    class Meta:
        model = PontoAtendimento
        fields = ['nome', 'ativo', 'responsaveis']
        widgets = {'responsaveis': forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsaveis'].queryset = Usuario.objects.filter(
            vinculos__clinica=self.clinica, vinculos__ativo=True, is_active=True).distinct().order_by('first_name',
                                                                                                     'username')


class ConfigPainelForm(ClinicaModelForm):
    class Meta:
        model = ConfigPainel
        fields = ['titulo', 'mensagem', 'voz_ativa', 'repeticoes']
