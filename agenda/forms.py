from datetime import timedelta
from decimal import Decimal

from django import forms
from django.utils import timezone

from contas.crud import ClinicaModelForm

from .models import Agendamento, BloqueioAgenda, ListaEspera, PacoteSessao


class AgendamentoForm(ClinicaModelForm):
    repetir = forms.IntegerField(
        label='Repetir semanalmente (nº de semanas)', required=False, min_value=0, max_value=52,
        help_text='Opcional: cria agendamentos nas próximas semanas no mesmo horário (útil para pacotes).')

    class Meta:
        model = Agendamento
        fields = ['paciente', 'medico', 'tipo', 'inicio', 'pacote', 'convenio', 'teleconsulta', 'valor', 'status',
                  'observacoes', 'notificar']

    def __init__(self, *args, medico_restrito=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['pacote'].queryset = PacoteSessao.objects.filter(
            clinica=self.clinica, status='ativo').select_related('paciente', 'tipo')
        self.fields['pacote'].required = False
        self.fields['valor'].help_text = 'Vazio = valor da tabela de preços (zero se for sessão de pacote).'
        if medico_restrito:
            self.fields['medico'].queryset = self.fields['medico'].queryset.filter(pk=medico_restrito.pk)
            self.fields['medico'].initial = medico_restrito.pk
        if self.instance.pk:
            del self.fields['repetir']
        else:
            self.fields['status'].choices = [c for c in Agendamento.STATUS if c[0] in ('agendado', 'confirmado')]

    def clean(self):
        d = super().clean()
        paciente, medico, tipo, inicio, pacote = (d.get(k) for k in ('paciente', 'medico', 'tipo', 'inicio',
                                                                     'pacote'))
        if not (paciente and medico and inicio):
            return d
        if pacote:
            if pacote.paciente_id != paciente.pk:
                self.add_error('pacote', 'Este pacote pertence a outro paciente.')
            elif pacote.vencido:
                self.add_error('pacote', 'Pacote com validade expirada.')
            else:
                d['tipo'] = tipo = pacote.tipo
                novas = 1 + (d.get('repetir') or 0)
                ja_conta = self.instance.pk and self.instance.pacote_id == pacote.pk
                if not ja_conta and pacote.disponiveis < novas:
                    self.add_error('pacote', f'Pacote sem saldo suficiente: {pacote.disponiveis} sessão(ões) '
                                             f'disponível(is) para agendar.')
        if not tipo:
            return d
        fim = inicio + timedelta(minutes=tipo.duracao_minutos or 30)
        d['fim'] = fim
        status = d.get('status') or 'agendado'
        if status not in ('cancelado', 'faltou'):
            conflitos = Agendamento.objects.filter(clinica=self.clinica, inicio__lt=fim, fim__gt=inicio).exclude(
                status__in=('cancelado', 'faltou'))
            if self.instance.pk:
                conflitos = conflitos.exclude(pk=self.instance.pk)
            c = conflitos.filter(medico=medico).select_related('paciente').first()
            bloqueio = BloqueioAgenda.conflitante(self.clinica, medico, inicio, fim)
            if bloqueio:
                self.add_error('inicio', f'Horário bloqueado: {bloqueio}.')
            elif c:
                self.add_error('inicio', f'Conflito: {medico} já possui atendimento com {c.paciente} às '
                                         f'{timezone.localtime(c.inicio):%H:%M}.')
            elif conflitos.filter(paciente=paciente).exists():
                self.add_error('inicio', 'O paciente já possui outro atendimento neste horário.')
        return d

    def save(self, commit=True):
        obj = super().save(commit=False)
        obj.tipo = self.cleaned_data['tipo']
        obj.fim = self.cleaned_data['fim']
        if 'valor' in self.changed_data or not obj.pk:
            obj.valor = self.cleaned_data.get('valor')
        elif {'tipo', 'convenio', 'pacote'} & set(self.changed_data):
            obj.valor = None  # recalcula pela tabela de preços
        if commit:
            obj.save()
        return obj


class PacoteForm(ClinicaModelForm):
    gerar_financeiro = forms.BooleanField(label='Gerar lançamento(s) no financeiro', required=False, initial=True)
    parcelas = forms.IntegerField(label='Parcelas', min_value=1, max_value=24, initial=1, required=False)
    ja_pago = forms.BooleanField(label='1ª parcela já recebida', required=False, initial=True)
    forma_pagamento = forms.ChoiceField(label='Forma de pagamento', required=False)

    class Meta:
        model = PacoteSessao
        fields = ['paciente', 'tipo', 'medico', 'quantidade', 'valor_total', 'data_compra', 'validade',
                  'faltas_consomem', 'status', 'observacoes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from financeiro.models import FORMAS_PAGAMENTO
        self.fields['forma_pagamento'].choices = FORMAS_PAGAMENTO
        self.fields['forma_pagamento'].widget.attrs['class'] = 'form-select'
        self.fields['tipo'].queryset = self.fields['tipo'].queryset.filter(permite_pacote=True)
        self.fields['valor_total'].help_text = 'Se ficar vazio/zerado, usa quantidade x valor por sessão da tabela.'
        self.fields['valor_total'].required = False
        if self.instance.pk:
            for c in ('gerar_financeiro', 'parcelas', 'ja_pago', 'forma_pagamento'):
                del self.fields[c]

    def clean(self):
        d = super().clean()
        tipo, qtd = d.get('tipo'), d.get('quantidade')
        if tipo and qtd and not d.get('valor_total'):
            unit = tipo.valor_sessao_pacote if tipo.valor_sessao_pacote is not None else tipo.valor
            d['valor_total'] = (unit or Decimal('0')) * qtd
        if self.instance.pk and qtd is not None and qtd < self.instance.usadas:
            self.add_error('quantidade', f'Já foram usadas {self.instance.usadas} sessões.')
        return d


class BloqueioForm(ClinicaModelForm):
    class Meta:
        model = BloqueioAgenda
        exclude = []

    def clean(self):
        d = super().clean()
        if d.get('inicio') and d.get('fim') and d['fim'] <= d['inicio']:
            self.add_error('fim', 'O fim deve ser depois do início.')
        return d


class ListaEsperaForm(ClinicaModelForm):
    class Meta:
        model = ListaEspera
        exclude = []
