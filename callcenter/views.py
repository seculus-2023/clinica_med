from django import forms
from django.contrib import messages
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from contas.crud import ClinicaModelForm, Crud, FormSimples
from contas.permissoes import acesso, tem_permissao

from .models import ContatoPaciente, InteracaoContato


class ContatoForm(ClinicaModelForm):
    class Meta:
        model = ContatoPaciente
        exclude = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.contrib.auth import get_user_model
        self.fields['responsavel'].queryset = get_user_model().objects.filter(
            vinculos__clinica=self.clinica, vinculos__ativo=True).distinct()


class InteracaoForm(FormSimples):
    canal = forms.ChoiceField(choices=InteracaoContato.CANAIS)
    resultado = forms.ChoiceField(choices=InteracaoContato.RESULTADOS)
    anotacao = forms.CharField(label='Anotação', widget=forms.Textarea, required=False)
    satisfacao = forms.TypedChoiceField(label='Satisfação do paciente (1 a 5)', required=False, coerce=int,
                                        empty_value=None, choices=[('', '-')] + [(i, str(i)) for i in range(1, 6)])
    nova_data = forms.DateField(label='Nova tentativa em', required=False,
                                help_text='Para "sem resposta" ou "recado": quando tentar de novo.')


class ContatoCrud(Crud):
    model, form_class = ContatoPaciente, ContatoForm
    modulo = 'callcenter'
    nome, nome_plural, url, icone = 'Contato', 'Contatos', 'callcenter:contato', 'bi-headset'
    url_sucesso = 'callcenter:fila'
    colunas = [('data_prevista', 'Data'), ('paciente', 'Paciente'), ('motivo', 'Motivo'), ('status', 'Status')]


@acesso('callcenter')
def fila(request):
    hoje = timezone.localdate()
    qs = ContatoPaciente.objects.filter(clinica=request.clinica).select_related('paciente', 'medico', 'responsavel')
    aba = request.GET.get('aba', 'hoje')
    if aba == 'hoje':
        qs = qs.filter(status__in=('pendente', 'em_andamento', 'sem_resposta'), data_prevista__lte=hoje)
    elif aba == 'futuros':
        qs = qs.filter(status__in=('pendente', 'em_andamento', 'sem_resposta'), data_prevista__gt=hoje)
    elif aba == 'concluidos':
        qs = qs.exclude(status__in=('pendente', 'em_andamento', 'sem_resposta')).order_by('-concluido_em')
    if request.GET.get('motivo'):
        qs = qs.filter(motivo=request.GET['motivo'])
    if request.GET.get('meus') == '1':
        qs = qs.filter(Q(responsavel=request.user) | Q(responsavel__isnull=True))
    base = ContatoPaciente.objects.filter(clinica=request.clinica)
    abertos = base.filter(status__in=('pendente', 'em_andamento', 'sem_resposta'))
    kpis = {
        'hoje': abertos.filter(data_prevista__lte=hoje).count(),
        'atrasados': abertos.filter(data_prevista__lt=hoje).count(),
        'futuros': abertos.filter(data_prevista__gt=hoje).count(),
        'satisfacao': base.aggregate(m=Avg('satisfacao'))['m'],
        'mes': base.filter(concluido_em__date__gte=hoje.replace(day=1)).count(),
    }
    return render(request, 'callcenter/fila.html', {
        'contatos': qs[:200], 'aba': aba, 'k': kpis, 'motivos': ContatoPaciente.MOTIVOS,
        'motivo_sel': request.GET.get('motivo', ''), 'pode_editar': tem_permissao(request, 'callcenter', 'editar'),
        'por_motivo': abertos.values('motivo').annotate(n=Count('id'))})


@acesso('callcenter')
def atender(request, pk):
    from notificacoes.services import montar_texto
    c = get_object_or_404(ContatoPaciente.objects.select_related('paciente', 'medico', 'agendamento'), pk=pk,
                          clinica=request.clinica)
    form = InteracaoForm(request.POST or None, initial={'satisfacao': c.satisfacao})
    if request.method == 'POST':
        if not tem_permissao(request, 'callcenter', 'editar'):
            messages.error(request, 'Sem permissão para registrar contatos.')
        elif form.is_valid():
            d = form.cleaned_data
            InteracaoContato.objects.create(contato=c, usuario=request.user, canal=d['canal'],
                                            resultado=d['resultado'], anotacao=d['anotacao'])
            c.tentativas += 1
            c.responsavel = c.responsavel or request.user
            if d['satisfacao']:
                c.satisfacao = d['satisfacao']
            if d['resultado'] in ('sem_resposta', 'recado'):
                c.status = 'sem_resposta'
                if d['nova_data']:
                    c.data_prevista = d['nova_data']
            else:
                c.status = d['resultado']
                c.concluido_em = timezone.now()
            c.save()
            messages.success(request, 'Interação registrada.')
            if d['resultado'] == 'reagendado' and tem_permissao(request, 'agenda', 'editar'):
                return redirect(f"/agenda/novo/?paciente={c.paciente_id}&medico={c.medico_id or ''}")
            return redirect('callcenter:fila')
    msg = montar_texto(request.clinica.msg_pos_consulta, request.clinica, c.paciente,
                       medico=c.medico, ag=c.agendamento)
    return render(request, 'callcenter/atender.html', {
        'c': c, 'form': form, 'interacoes': c.interacoes.select_related('usuario'), 'msg_whatsapp': msg,
        'historico': c.paciente.agendamentos.select_related('medico', 'tipo').order_by('-inicio')[:6]})
