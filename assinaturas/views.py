"""Cadastro público de clínicas (teste grátis), painel do dono do sistema e "Minha assinatura"."""
from datetime import timedelta

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from contas.crud import FormSimples, estilizar_campos
from contas.models import Clinica, Vinculo
from contas.permissoes import acesso, superusuario

from .models import Assinatura, Fatura, PlanoSaaS
from .pix import br_code

Usuario = get_user_model()


def saas_ativo():
    return getattr(settings, 'SAAS_ATIVO', False)


def pix_da_fatura(f):
    chave = getattr(settings, 'SAAS_PIX_CHAVE', '')
    if not chave:
        return ''
    return br_code(chave, settings.SAAS_PIX_NOME, settings.SAAS_PIX_CIDADE, float(f.valor), f.txid,
                   f'Fatura {f.competencia}')


# ------------------------------------------------------------------ cadastro público
class CadastroForm(FormSimples):
    clinica = forms.CharField(label='Nome da clínica', max_length=150)
    cnpj = forms.CharField(label='CNPJ (opcional)', max_length=20, required=False)
    cidade = forms.CharField(max_length=100)
    uf = forms.CharField(label='UF', max_length=2)
    whatsapp = forms.CharField(label='WhatsApp da clínica', max_length=20)
    nome = forms.CharField(label='Seu nome', max_length=150)
    email = forms.EmailField(label='Seu e-mail')
    usuario = forms.CharField(label='Usuário para login', max_length=150)
    senha = forms.CharField(label='Senha', widget=forms.PasswordInput, min_length=8)
    plano = forms.ModelChoiceField(PlanoSaaS.objects.none(), label='Plano', widget=forms.RadioSelect, empty_label=None)
    aceite = forms.BooleanField(label='Li e aceito os termos de uso e a política de privacidade (LGPD)')
    site = forms.CharField(required=False, widget=forms.HiddenInput)   # honeypot

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plano'].queryset = PlanoSaaS.objects.filter(ativo=True, publico=True)
        estilizar_campos(self)

    def clean_usuario(self):
        u = self.cleaned_data['usuario'].strip()
        if Usuario.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError('Este usuário já existe. Escolha outro.')
        return u

    def clean_email(self):
        e = self.cleaned_data['email'].strip().lower()
        if Usuario.objects.filter(email__iexact=e).exists():
            raise forms.ValidationError('Já existe uma conta com este e-mail. Fale com o suporte.')
        return e


def cadastro(request):
    if not saas_ativo() or not getattr(settings, 'SAAS_CADASTRO_ABERTO', False):
        raise Http404
    form = CadastroForm(request.POST or None, initial={'plano': PlanoSaaS.objects.filter(ativo=True, publico=True).first()})
    if request.method == 'POST' and form.is_valid() and not form.cleaned_data['site']:
        from contas.services import preparar_clinica
        d = form.cleaned_data
        with transaction.atomic():
            c = Clinica.objects.create(nome=d['clinica'], cnpj=d['cnpj'], cidade=d['cidade'], uf=d['uf'].upper()[:2],
                                       whatsapp=d['whatsapp'], email=d['email'])
            perfis = preparar_clinica(c)
            nomes = d['nome'].split(' ', 1)
            u = Usuario.objects.create_user(username=d['usuario'], email=d['email'], password=d['senha'],
                                            first_name=nomes[0], last_name=nomes[1] if len(nomes) > 1 else '')
            Vinculo.objects.create(usuario=u, clinica=c, perfil=perfis['Administrador'])
            Assinatura.objects.create(clinica=c, plano=d['plano'], status='teste', responsavel_email=d['email'],
                                      teste_ate=timezone.localdate() + timedelta(days=d['plano'].dias_teste),
                                      dia_vencimento=min(timezone.localdate().day, 28))
        login(request, u, backend='django.contrib.auth.backends.ModelBackend')
        request.session['clinica_id'] = c.pk
        messages.success(request, f'Bem-vindo(a)! Sua clínica foi criada com {d["plano"].dias_teste} dias de teste grátis.')
        return redirect('painel:dashboard')
    return render(request, 'assinaturas/cadastro.html', {'form': form, 'nome_sistema': settings.SAAS_NOME})


# ------------------------------------------------------------------ minha assinatura (clínica)
@acesso('administrativo')
def minha(request):
    a = Assinatura.objects.filter(clinica=request.clinica).select_related('plano').first()
    faturas = list(a.faturas.all()[:24]) if a else []
    for f in faturas:
        f.pix = pix_da_fatura(f) if f.status == 'pendente' else ''
    return render(request, 'assinaturas/minha.html', {'a': a, 'faturas': faturas,
                                                      'planos': PlanoSaaS.objects.filter(ativo=True, publico=True)})


def bloqueado(request):
    a = Assinatura.objects.filter(clinica=request.clinica).select_related('plano').first() if request.clinica else None
    faturas = list(a.faturas.filter(status='pendente')) if a else []
    for f in faturas:
        f.pix = pix_da_fatura(f)
    return render(request, 'assinaturas/bloqueado.html', {'a': a, 'faturas': faturas}, status=402)


# ------------------------------------------------------------------ painel do dono do sistema
class PlanoForm(forms.ModelForm):
    class Meta:
        model = PlanoSaaS
        exclude = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        estilizar_campos(self)


@superusuario
def painel(request):
    hoje = timezone.localdate()
    assinaturas = Assinatura.objects.select_related('clinica', 'plano').order_by('clinica__nome')
    sem = Clinica.objects.filter(assinatura__isnull=True)
    from django.db.models import Sum
    mrr = assinaturas.filter(status='ativa').aggregate(s=Sum('plano__preco_mensal'))['s'] or 0
    pend = Fatura.objects.filter(status='pendente').aggregate(s=Sum('valor'))['s'] or 0
    return render(request, 'assinaturas/painel.html', {
        'assinaturas': assinaturas, 'sem': sem, 'planos': PlanoSaaS.objects.all(), 'mrr': mrr, 'pend': pend,
        'faturas': Fatura.objects.select_related('assinatura__clinica').filter(status='pendente')[:50],
        'hoje': hoje, 'ativo': saas_ativo(), 'status': Assinatura.STATUS})


@superusuario
def plano_form(request, pk=None):
    obj = get_object_or_404(PlanoSaaS, pk=pk) if pk else None
    form = PlanoForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Plano salvo.')
        return redirect('assinaturas:painel')
    return render(request, 'form_simples.html', {'form': form, 'titulo': 'Plano', 'voltar': 'assinaturas:painel'})


@superusuario
@require_POST
def acao(request):
    from django.utils.dateparse import parse_date
    acao = request.POST.get('acao')
    if acao == 'criar':
        c = get_object_or_404(Clinica, pk=request.POST.get('clinica'))
        plano = get_object_or_404(PlanoSaaS, pk=request.POST.get('plano'))
        Assinatura.objects.get_or_create(clinica=c, defaults={'plano': plano, 'status': 'ativa'})
    elif acao == 'atualizar':
        a = get_object_or_404(Assinatura, pk=request.POST.get('assinatura'))
        a.plano = get_object_or_404(PlanoSaaS, pk=request.POST.get('plano'))
        if request.POST.get('status') in dict(Assinatura.STATUS):
            a.status = request.POST['status']
        a.dia_vencimento = max(1, min(28, int(request.POST.get('dia_vencimento') or a.dia_vencimento)))
        a.save()
        messages.success(request, f'Assinatura de {a.clinica} atualizada.')
    elif acao == 'gerar':
        from .tarefas import gerar_faturas
        n = gerar_faturas(forcar=True)
        messages.success(request, f'{n} fatura(s) gerada(s).')
    elif acao == 'pagar':
        f = get_object_or_404(Fatura, pk=request.POST.get('fatura'))
        f.status, f.pago_em, f.forma = 'paga', parse_date(request.POST.get('data', '')) or timezone.localdate(), \
            request.POST.get('forma', 'pix')[:30]
        f.save()
        a = f.assinatura
        if a.status in ('teste', 'inadimplente', 'suspensa'):
            a.status = 'ativa'
            a.save(update_fields=['status'])
        messages.success(request, f'Fatura {f.competencia} de {a.clinica} marcada como paga.')
    elif acao == 'cancelar_fatura':
        Fatura.objects.filter(pk=request.POST.get('fatura')).update(status='cancelada')
    return redirect('assinaturas:painel')
