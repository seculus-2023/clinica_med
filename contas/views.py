from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.views import LoginView
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .crud import Crud, estilizar_campos
from .forms import ClinicaForm, ConfiguracaoClinicaForm, LembreteForm, LoginForm, PerfilForm, UsuarioClinicaForm
from .models import Clinica, Lembrete, Perfil, Vinculo
from .permissoes import acesso, superusuario
from .services import preparar_clinica

Usuario = get_user_model()


class Entrar(LoginView):
    template_name = 'contas/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True


@login_required
def selecionar_clinica(request):
    if request.user.is_superuser:
        clinicas = Clinica.objects.filter(ativa=True)
    else:
        clinicas = Clinica.objects.filter(vinculos__usuario=request.user, vinculos__ativo=True, ativa=True)
    escolha = request.GET.get('id') or request.POST.get('id')
    if escolha and clinicas.filter(pk=escolha).exists():
        request.session['clinica_id'] = int(escolha)
        prox = request.GET.get('next', '')
        return redirect(prox if prox.startswith('/') else 'painel:dashboard')
    if clinicas.count() == 1 and not request.GET.get('trocar'):
        request.session['clinica_id'] = clinicas.first().pk
        return redirect('painel:dashboard')
    return render(request, 'contas/selecionar_clinica.html', {'clinicas': clinicas})


# ---------------- Clínicas (somente superusuário) ----------------
@superusuario
def clinicas(request):
    return render(request, 'contas/clinicas.html', {'clinicas': Clinica.objects.all()})


@superusuario
def clinica_form(request, pk=None):
    obj = get_object_or_404(Clinica, pk=pk) if pk else None
    form = ClinicaForm(request.POST or None, request.FILES or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        clinica = form.save()
        if not obj:
            perfis = preparar_clinica(clinica)
            Vinculo.objects.get_or_create(usuario=request.user, clinica=clinica,
                                          defaults={'perfil': perfis['Administrador']})
        messages.success(request, 'Clínica salva.')
        return redirect('contas:clinicas')
    return render(request, 'form_simples.html', {
        'form': form, 'titulo': 'Editar clínica' if obj else 'Nova clínica', 'voltar': 'contas:clinicas',
        'multipart': True})


# ---------------- Configurações da clínica ativa ----------------
@acesso('administrativo', 'editar')
def configuracoes(request):
    form = ConfiguracaoClinicaForm(request.POST or None, request.FILES or None, instance=request.clinica)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configurações salvas.')
        return redirect('contas:configuracoes')
    from django.conf import settings
    from django.urls import reverse
    link = settings.SITE_URL + reverse('agenda:online', args=[request.clinica.codigo_publico])
    return render(request, 'contas/configuracoes.html', {'form': form, 'link_online': link})


# ---------------- Usuários da clínica ----------------
@acesso('administrativo', 'ver')
def usuarios(request):
    vinculos = Vinculo.objects.filter(clinica=request.clinica).select_related('usuario', 'perfil')
    q = request.GET.get('q', '').strip()
    if q:
        vinculos = vinculos.filter(Q(usuario__username__icontains=q) | Q(usuario__first_name__icontains=q) |
                                   Q(usuario__email__icontains=q))
    return render(request, 'contas/usuarios.html', {'vinculos': vinculos.order_by('usuario__first_name'), 'q': q})


@acesso('administrativo', 'editar')
def usuario_form(request, pk=None):
    vinculo = get_object_or_404(Vinculo, pk=pk, clinica=request.clinica) if pk else None
    usuario = vinculo.usuario if vinculo else None
    inicial = {}
    if vinculo:
        inicial = {'username': usuario.username, 'first_name': usuario.first_name, 'last_name': usuario.last_name,
                   'email': usuario.email, 'telefone': usuario.telefone, 'perfil': vinculo.perfil,
                   'ativo': vinculo.ativo}
    form = UsuarioClinicaForm(request.POST or None, initial=inicial, clinica=request.clinica, usuario=usuario)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        u = usuario or Usuario()
        for campo in ('username', 'first_name', 'last_name', 'email', 'telefone'):
            setattr(u, campo, d[campo])
        if d['senha']:
            u.set_password(d['senha'])
        u.save()
        if vinculo:
            vinculo.perfil = d['perfil']
            vinculo.ativo = d['ativo']
            vinculo.save()
        else:
            Vinculo.objects.create(usuario=u, clinica=request.clinica, perfil=d['perfil'], ativo=d['ativo'])
        messages.success(request, 'Usuário salvo.')
        return redirect('contas:usuarios')
    return render(request, 'form_simples.html', {
        'form': form, 'titulo': 'Editar usuário' if vinculo else 'Novo usuário', 'voltar': 'contas:usuarios'})


# ---------------- Perfis de acesso ----------------
@acesso('administrativo', 'ver')
def perfis(request):
    lista = Perfil.objects.filter(clinica=request.clinica)
    return render(request, 'contas/perfis.html', {'perfis': lista})


@acesso('administrativo', 'editar')
def perfil_form(request, pk=None):
    obj = get_object_or_404(Perfil, pk=pk, clinica=request.clinica) if pk else None
    form = PerfilForm(request.POST or None, instance=obj, clinica=request.clinica)
    if request.method == 'POST' and form.is_valid():
        p = form.save(commit=False)
        if not p.pk:
            p.clinica = request.clinica
        p.save()
        messages.success(request, 'Perfil salvo.')
        return redirect('contas:perfis')
    return render(request, 'contas/perfil_form.html', {'form': form, 'obj': obj})


# ---------------- Lembretes ----------------
class LembreteCrud(Crud):
    model = Lembrete
    form_class = LembreteForm
    modulo = None
    nome, nome_plural = 'Lembrete', 'Lembretes'
    url = 'contas:lembrete'
    icone = 'bi-bell'
    colunas = [('data_hora', 'Quando'), ('titulo', 'Título'), ('usuario', 'Para'), ('origem', 'Origem'),
               ('concluido', 'Concluído')]
    busca = ['titulo', 'mensagem']
    filtros = [('concluido', 'Situação', [('False', 'Pendentes'), ('True', 'Concluídos')])]
    acoes_linha = [('contas:lembrete_concluir', 'bi-check2-circle', 'Concluir', 'post')]

    @classmethod
    def antes_salvar(cls, request, obj, form):
        if not obj.criado_por_id:
            obj.criado_por = request.user
        if 'data_hora' in form.changed_data or 'enviar_email' in form.changed_data:
            obj.email_enviado = False

    @classmethod
    def queryset(cls, request):
        return Lembrete.objects.filter(clinica=request.clinica).filter(
            Q(usuario=request.user) | Q(usuario__isnull=True) | Q(criado_por=request.user)
        ).order_by('concluido', '-data_hora')


@login_required
@require_POST
def lembrete_concluir(request, pk):
    lem = get_object_or_404(Lembrete.objects.filter(Q(usuario=request.user) | Q(usuario__isnull=True)),
                            pk=pk, clinica=request.clinica)
    lem.concluido = True
    lem.save(update_fields=['concluido', 'atualizado_em'])
    prox = request.POST.get('next', '')
    if lem.link and request.POST.get('abrir'):
        return redirect(lem.link)
    return redirect(prox if prox.startswith('/') else 'contas:lembrete_list')


# ---------------- Minha conta ----------------
@login_required
def minha_conta(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    estilizar_campos(form)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        update_session_auth_hash(request, user)
        messages.success(request, 'Senha alterada com sucesso.')
        return redirect('painel:dashboard')
    return render(request, 'form_simples.html', {'form': form, 'titulo': 'Alterar minha senha',
                                                 'voltar': 'painel:dashboard'})
