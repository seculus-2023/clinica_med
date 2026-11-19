"""Campanhas segmentadas (CRM): aniversário, prevenção por faixa etária, reativação de pacientes etc."""
from datetime import timedelta

from django import forms
from django.contrib import messages
from django.db.models import Max, Q
from django.shortcuts import redirect, render
from django.utils import timezone

from cadastros.models import Especialidade, Paciente
from contas.crud import FormSimples
from contas.permissoes import acesso

from .models import Campanha
from .services import enfileirar, montar_texto


class CampanhaForm(FormSimples):
    nome = forms.CharField(label='Nome da campanha', max_length=120)
    mensagem = forms.CharField(label='Mensagem', widget=forms.Textarea(attrs={'rows': 5}),
                               help_text='Variáveis: {paciente} {paciente_completo} {clinica} {telefone_clinica} '
                                         '{whatsapp_clinica} {endereco}')
    canal_whatsapp = forms.BooleanField(label='Enviar por WhatsApp', required=False, initial=True)
    canal_email = forms.BooleanField(label='Enviar por e-mail', required=False, initial=True)
    canal_sms = forms.BooleanField(label='Enviar por SMS', required=False)
    sexo = forms.ChoiceField(label='Sexo', required=False, choices=[('', 'Todos')] + Paciente.SEXO)
    idade_min = forms.IntegerField(label='Idade mínima', required=False, min_value=0)
    idade_max = forms.IntegerField(label='Idade máxima', required=False, min_value=0)
    convenio = forms.CharField(label='Convênio (contém)', required=False)
    aniversariantes_mes = forms.BooleanField(label='Somente aniversariantes do mês', required=False)
    sem_consulta_dias = forms.IntegerField(label='Sem atendimento há mais de (dias)', required=False, min_value=1,
                                           help_text='Reativação: pacientes que não vêm há X dias.')
    especialidade = forms.ModelChoiceField(label='Já atendidos na especialidade', required=False,
                                           queryset=Especialidade.objects.none())
    origem = forms.ChoiceField(label='Origem do paciente', required=False, choices=Paciente.ORIGENS)

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['especialidade'].queryset = Especialidade.objects.filter(clinica=clinica)
        self.fields['especialidade'].widget.attrs['class'] = 'form-select'


def _anos_atras(d, n):
    try:
        return d.replace(year=d.year - n)
    except ValueError:  # 29/02
        return d.replace(year=d.year - n, day=28)


def segmentar(clinica, d):
    hoje = timezone.localdate()
    qs = Paciente.objects.filter(clinica=clinica, ativo=True, aceita_campanhas=True)
    if d.get('sexo'):
        qs = qs.filter(sexo=d['sexo'])
    if d.get('idade_min') is not None:
        qs = qs.filter(data_nascimento__lte=_anos_atras(hoje, d['idade_min']))
    if d.get('idade_max') is not None:
        qs = qs.filter(data_nascimento__gt=_anos_atras(hoje, d['idade_max'] + 1))
    if d.get('convenio'):
        qs = qs.filter(convenio__icontains=d['convenio'])
    if d.get('aniversariantes_mes'):
        qs = qs.filter(data_nascimento__month=hoje.month)
    if d.get('origem'):
        qs = qs.filter(origem=d['origem'])
    if d.get('especialidade'):
        qs = qs.filter(agendamentos__tipo__especialidade=d['especialidade'], agendamentos__status='concluido')
    if d.get('sem_consulta_dias'):
        limite = timezone.now() - timedelta(days=d['sem_consulta_dias'])
        qs = qs.annotate(ult=Max('agendamentos__inicio', filter=Q(agendamentos__status='concluido'))).filter(
            ult__lt=limite)
    return qs.distinct()


@acesso('callcenter', 'editar')
def campanhas(request):
    form = CampanhaForm(request.POST or None, clinica=request.clinica)
    previa = None
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        alvo = segmentar(request.clinica, d)
        if request.POST.get('enviar'):
            if not (d['canal_whatsapp'] or d['canal_email'] or d['canal_sms']):
                messages.error(request, 'Escolha ao menos um canal.')
            else:
                total = 0
                for p in alvo:
                    ids = enfileirar(request.clinica, p.nome,
                                     telefone=p.celular if d['canal_whatsapp'] and p.aceita_whatsapp else None,
                                     email=p.email if d['canal_email'] and p.aceita_email else None,
                                     sms=d['canal_sms'] and p.aceita_sms,
                                     assunto=d['nome'], mensagem=montar_texto(d['mensagem'], request.clinica, p),
                                     evento='campanha')
                    total += bool(ids)
                filtros = {k: (str(v) if v not in (None, '') else None) for k, v in d.items()
                           if k not in ('nome', 'mensagem')}
                Campanha.objects.create(clinica=request.clinica, nome=d['nome'], mensagem=d['mensagem'],
                                        filtros=filtros, total=total, criado_por=request.user)
                messages.success(request, f'Campanha "{d["nome"]}" enviada para {total} paciente(s).')
                return redirect('notificacoes:campanhas')
        previa = list(alvo[:50])
        form.total = alvo.count()
        form.exemplo = montar_texto(d['mensagem'], request.clinica, previa[0]) if previa else ''
    return render(request, 'notificacoes/campanhas.html', {
        'form': form, 'previa': previa, 'historico': Campanha.objects.filter(clinica=request.clinica)[:20]})
