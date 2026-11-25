"""Páginas públicas (sem login): agendamento online, check-in digital e pesquisa NPS."""
from datetime import timedelta

from django import forms
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime

from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.crud import FormSimples, estilizar_campos
from contas.models import Clinica, Lembrete

from . import marcacao
from .disponibilidade import horarios_livres
from .models import Agendamento, AvaliacaoNPS

TEXTO_LGPD = ('Autorizo a clínica a tratar meus dados pessoais e de saúde para fins de atendimento, agendamento, '
              'faturamento e contato, conforme a Lei 13.709/2018 (LGPD). Posso revogar este consentimento a qualquer '
              'momento.')


def _digitos(s):
    return ''.join(c for c in str(s or '') if c.isdigit())


class OnlineForm(FormSimples):
    nome = forms.CharField(label='Nome completo', max_length=150)
    celular = forms.CharField(label='Celular / WhatsApp', max_length=20)
    email = forms.EmailField(label='E-mail', required=False)
    cpf = forms.CharField(label='CPF', max_length=14, required=False)
    data_nascimento = forms.DateField(label='Data de nascimento', required=False)
    lgpd = forms.BooleanField(label=TEXTO_LGPD)
    site = forms.CharField(required=False, widget=forms.HiddenInput)  # honeypot anti-robô

    def clean_celular(self):
        d = _digitos(self.cleaned_data['celular'])
        if len(d) < 10:
            raise forms.ValidationError('Informe o celular com DDD.')
        return self.cleaned_data['celular']


def online(request, codigo):
    clinica = get_object_or_404(Clinica, codigo_publico=codigo, ativa=True)
    clinica.ativar_fuso()
    if not clinica.agendamento_online:
        return render(request, 'agenda/publico/online.html', {'c': clinica, 'fechado': True})
    ctx = marcacao.contexto(clinica, request.GET, publico=True)
    tipo, medico = ctx['tipo'], ctx['medico']
    slot = parse_datetime(request.GET.get('slot', '') or request.POST.get('slot', ''))
    form = OnlineForm(request.POST or None)
    if request.method == 'POST' and tipo and medico and slot and form.is_valid():
        if form.cleaned_data['site']:
            return redirect(request.path)
        slot = timezone.localtime(slot) if timezone.is_aware(slot) else timezone.make_aware(slot)
        if slot not in horarios_livres(clinica, medico, tipo, slot.date()):
            form.add_error(None, 'Este horário acabou de ser ocupado. Escolha outro.')
        else:
            d = form.cleaned_data
            with transaction.atomic():
                cel, cpf = _digitos(d['celular']), _digitos(d['cpf'])
                paciente = None
                candidatos = Paciente.objects.filter(clinica=clinica).filter(
                    Q(celular__endswith=cel[-4:]) | (Q(cpf__endswith=cpf[-2:]) if cpf else Q(pk=0)))
                for p in candidatos:
                    if (cpf and _digitos(p.cpf) == cpf) or (_digitos(p.celular)[-9:] == cel[-9:]):
                        paciente = p
                        break
                if not paciente:
                    paciente = Paciente.objects.create(
                        clinica=clinica, nome=d['nome'], celular=d['celular'], email=d['email'] or '',
                        cpf=d['cpf'] or '', data_nascimento=d['data_nascimento'], origem='online')
                if not paciente.consentimento_lgpd_em:
                    paciente.consentimento_lgpd_em = timezone.now()
                    paciente.save(update_fields=['consentimento_lgpd_em'])
                ag = Agendamento.objects.create(clinica=clinica, paciente=paciente, medico=medico, tipo=tipo,
                                                inicio=slot, origem='online', notificar=True)
                Lembrete.objects.create(clinica=clinica, origem='online',
                                        titulo=f'Agendamento online: {paciente} - {slot:%d/%m %H:%M}',
                                        mensagem=f'{tipo} com {medico}', link=reverse('agenda:detalhe', args=[ag.pk]))
            return redirect('agenda:confirmar_publico', ag.token)
    if slot:
        slot = timezone.localtime(slot) if timezone.is_aware(slot) else timezone.make_aware(slot)
    ctx.update({'c': clinica, 'slot': slot, 'form': form})
    return render(request, 'agenda/publico/online.html', ctx)


def grade_publica(request, codigo):
    clinica = get_object_or_404(Clinica, codigo_publico=codigo, ativa=True)
    clinica.ativar_fuso()
    return render(request, 'agenda/publico/grade.html', {
        'c': clinica, 'linhas': marcacao.grade_completa(clinica, publico=True), 'dias': marcacao.DIAS_CURTOS})


class CheckinForm(forms.ModelForm):
    lgpd = forms.BooleanField(label=TEXTO_LGPD)

    class Meta:
        model = Paciente
        fields = ['nome', 'cpf', 'rg', 'data_nascimento', 'sexo', 'celular', 'email', 'cep', 'endereco', 'numero',
                  'bairro', 'cidade', 'uf', 'convenio', 'carteirinha', 'responsavel', 'alergias', 'origem']
        labels = {'alergias': 'Possui alergias? Quais?'}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        estilizar_campos(self)
        for f in ('cpf', 'data_nascimento', 'celular'):
            self.fields[f].required = True


def checkin(request, token):
    ag = get_object_or_404(Agendamento.objects.select_related('paciente', 'clinica', 'medico', 'tipo'), token=token)
    ag.clinica.ativar_fuso()
    if ag.status in ('cancelado', 'concluido', 'faltou'):
        return render(request, 'agenda/publico/checkin.html', {'c': ag.clinica, 'ag': ag, 'encerrado': True})
    form = CheckinForm(request.POST or None, instance=ag.paciente, initial={'lgpd': bool(ag.paciente.consentimento_lgpd_em)})
    if request.method == 'POST' and form.is_valid():
        p = form.save(commit=False)
        p.consentimento_lgpd_em = p.consentimento_lgpd_em or timezone.now()
        p.save()
        ag.checkin_em = timezone.now()
        if ag.status == 'agendado':
            ag.status, ag.confirmado_em, ag.confirmado_por = 'confirmado', timezone.now(), 'paciente'
        ag.save()
        return render(request, 'agenda/publico/checkin.html', {'c': ag.clinica, 'ag': ag, 'feito': True})
    return render(request, 'agenda/publico/checkin.html', {'c': ag.clinica, 'ag': ag, 'form': form})


TERMO_TELE = (
    'Declaro que fui informado(a) de que a teleconsulta é realizada por vídeo, conforme a Resolução CFM nº 2.314/2022 '
    'e a Lei nº 14.510/2022; que posso solicitar atendimento presencial a qualquer momento; que o profissional pode '
    'interromper a teleconsulta e indicar avaliação presencial quando necessário; e que os dados serão registrados no '
    'meu prontuário com sigilo, conforme a LGPD. Comprometo-me a estar em local reservado durante o atendimento.')


class TeleForm(FormSimples):
    aceito = forms.BooleanField(label='Li e aceito o termo de consentimento da teleconsulta')
    gravacao = forms.BooleanField(label='Autorizo a gravação da teleconsulta, que ficará arquivada no meu prontuário '
                                        'com acesso restrito (opcional)', required=False)


def teleconsulta(request, token):
    ag = get_object_or_404(Agendamento.objects.select_related('clinica', 'medico', 'paciente', 'tipo'), token=token)
    ag.clinica.ativar_fuso()
    if not ag.teleconsulta or ag.status in ('cancelado', 'faltou'):
        return render(request, 'agenda/publico/teleconsulta.html', {'c': ag.clinica, 'ag': ag, 'indisponivel': True})
    form = TeleForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
        ag.tele_consentimento_em = timezone.now()
        ag.tele_autoriza_gravacao = form.cleaned_data['gravacao']
        ag.tele_consentimento_ip = ip or None
        if ag.status == 'agendado':
            ag.status, ag.confirmado_em, ag.confirmado_por = 'confirmado', timezone.now(), 'paciente'
        ag.save()
        return redirect('agenda:teleconsulta', token)
    inicio = timezone.localtime(ag.inicio)
    liberada = timezone.now() >= ag.inicio - timedelta(minutes=30)
    return render(request, 'agenda/publico/teleconsulta.html', {
        'c': ag.clinica, 'ag': ag, 'form': form, 'termo': TERMO_TELE, 'liberada': liberada, 'inicio': inicio})


class NPSForm(FormSimples):
    ESCALA = [(i, str(i)) for i in range(11)]
    nota = forms.TypedChoiceField(label='De 0 a 10, quanto você recomendaria a clínica a um amigo ou familiar?',
                                  choices=ESCALA, coerce=int, widget=forms.RadioSelect)
    nota_medico = forms.TypedChoiceField(label='Nota para o atendimento do profissional', choices=ESCALA, coerce=int,
                                         widget=forms.RadioSelect, required=False, empty_value=None)
    nota_recepcao = forms.TypedChoiceField(label='Nota para a recepção / atendimento da equipe', choices=ESCALA,
                                           coerce=int, widget=forms.RadioSelect, required=False, empty_value=None)
    comentario = forms.CharField(label='Quer deixar um comentário?', widget=forms.Textarea, required=False)


def avaliar(request, token):
    ag = get_object_or_404(Agendamento.objects.select_related('clinica', 'medico', 'paciente'), token=token)
    ag.clinica.ativar_fuso()
    existente = AvaliacaoNPS.objects.filter(agendamento=ag).first()
    if existente or ag.status != 'concluido':
        return render(request, 'agenda/publico/avaliar.html', {'c': ag.clinica, 'ag': ag, 'av': existente,
                                                               'indisponivel': not existente})
    form = NPSForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        av = AvaliacaoNPS.objects.create(clinica=ag.clinica, agendamento=ag, nota=d['nota'],
                                         nota_medico=d['nota_medico'], nota_recepcao=d['nota_recepcao'],
                                         comentario=d['comentario'])
        from callcenter.models import ContatoPaciente
        ContatoPaciente.objects.filter(agendamento=ag, motivo='pos_consulta', status='pendente').update(
            satisfacao=max(1, round(av.nota / 2)))
        if av.classificacao == 'detrator':
            Lembrete.objects.create(clinica=ag.clinica, origem='nps', titulo=f'Avaliação baixa (NPS {av.nota}): {ag.paciente}',
                                    mensagem=av.comentario, link=reverse('agenda:detalhe', args=[ag.pk]))
        from ouvidoria.services import abrir_por_nps
        manifestacao = abrir_por_nps(av)
        return render(request, 'agenda/publico/avaliar.html', {'c': ag.clinica, 'ag': ag, 'av': av, 'obrigado': True,
                                                               'manifestacao': manifestacao})
    return render(request, 'agenda/publico/avaliar.html', {'c': ag.clinica, 'ag': ag, 'form': form})
