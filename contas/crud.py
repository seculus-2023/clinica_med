"""Infraestrutura genérica: formulário por clínica, mixins de acesso e CRUD reutilizável."""
import datetime
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, UpdateView

from .permissoes import tem_permissao


def moeda(valor):
    if valor is None or valor == '':
        return '-'
    v = f'{Decimal(valor):,.2f}'
    return 'R$ ' + v.replace(',', 'X').replace('.', ',').replace('X', '.')


class Autocomplete(forms.Widget):
    """Campo com busca dinâmica (para tabelas grandes: CMED, SIGTAP, CID).

    modo='id'   -> grava a PK (ForeignKey); exibe o texto do objeto.
    modo='texto'-> grava o próprio texto/código escolhido (CharField).
    """
    template_name = 'widgets/autocomplete.html'

    def __init__(self, url_name, model=None, modo='id', campo_valor='codigo', attrs=None):
        super().__init__(attrs)
        self.url_name, self.model, self.modo, self.campo_valor = url_name, model, modo, campo_valor

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        rotulo = ''
        if value not in (None, ''):
            if self.modo == 'id' and self.model is not None:
                obj = self.model.objects.filter(pk=value).first()
                rotulo = str(obj) if obj else ''
            else:
                rotulo = value
        ctx['widget'].update({'url': reverse(self.url_name), 'rotulo': rotulo, 'modo': self.modo,
                              'campo_valor': self.campo_valor})
        return ctx


def estilizar_campos(form):
    for field in form.fields.values():
        w = field.widget
        if isinstance(field, forms.DateTimeField) and not isinstance(w, forms.HiddenInput):
            field.widget = w = forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M')
            field.input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M', '%d/%m/%Y %H:%M']
        elif isinstance(field, forms.DateField) and not isinstance(w, forms.HiddenInput):
            field.widget = w = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')
            field.input_formats = ['%Y-%m-%d', '%d/%m/%Y']
        elif isinstance(field, forms.TimeField):
            field.widget = w = forms.TimeInput(attrs={'type': 'time'}, format='%H:%M')
        elif isinstance(field, (forms.DecimalField, forms.FloatField)) and not isinstance(w, forms.HiddenInput):
            # aceita vírgula decimal (padrão brasileiro): "95,00" e exibe valores como "95,00"
            field.localize = True
            field.widget = w = forms.TextInput(attrs={'inputmode': 'decimal', **{k: v for k, v in w.attrs.items()
                                                                                if k in ('placeholder',)}})
            w.is_localized = True
        if isinstance(w, (forms.CheckboxInput,)):
            css = 'form-check-input'
        elif isinstance(w, forms.CheckboxSelectMultiple):
            css = ''
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            css = 'form-select'
        else:
            css = 'form-control'
        if css:
            w.attrs['class'] = (w.attrs.get('class', '') + ' ' + css).strip()
        if isinstance(w, forms.Textarea):
            w.attrs.setdefault('rows', 3)


class ClinicaModelForm(forms.ModelForm):
    """ModelForm que restringe as escolhas de chaves estrangeiras à clínica ativa."""

    def __init__(self, *args, clinica=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinica = clinica
        for field in self.fields.values():
            if isinstance(field, forms.ModelChoiceField):
                model = field.queryset.model
                nomes = {f.name for f in model._meta.get_fields()}
                if 'clinica' in nomes and clinica is not None:
                    field.queryset = field.queryset.filter(clinica=clinica)
                if 'ativo' in nomes and not self.instance.pk:
                    field.queryset = field.queryset.filter(ativo=True)
        estilizar_campos(self)


class FormSimples(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        estilizar_campos(self)


class AcessoMixin:
    modulo = None
    acao = 'ver'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('contas:login')
        if request.clinica is None:
            return redirect('contas:selecionar_clinica')
        if self.modulo and not tem_permissao(request, self.modulo, self.acao):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def valor_coluna(obj, attr, fmt=None):
    valor = obj
    for parte in attr.split('__'):
        if valor is None:
            break
        display = getattr(valor, f'get_{parte}_display', None)
        valor = display() if display else getattr(valor, parte, None)
        if callable(valor) and not hasattr(valor, 'all'):
            valor = valor()
    if hasattr(valor, 'all'):
        valor = ', '.join(str(v) for v in valor.all())
    if fmt == 'moeda':
        return moeda(valor)
    if valor is None or valor == '':
        return '-'
    if isinstance(valor, bool):
        return 'Sim' if valor else 'Não'
    if isinstance(valor, datetime.datetime):
        return timezone.localtime(valor).strftime('%d/%m/%Y %H:%M')
    if isinstance(valor, datetime.date):
        return valor.strftime('%d/%m/%Y')
    if isinstance(valor, Decimal):
        return f'{valor:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return str(valor)


class Crud:
    """Configuração declarativa de um cadastro.

    model, form_class, modulo, nome, nome_plural, url (namespace:prefixo), icone,
    colunas = [(atributo, rótulo[, formato])], busca = [campos], acoes_linha = [(url_name, ícone, título)]
    """
    model = None
    form_class = None
    modulo = 'cadastros'
    nome = ''
    nome_plural = ''
    url = ''
    icone = 'bi-list'
    colunas = []
    busca = []
    ordenacao = None
    acoes_linha = []
    filtros = []  # [(campo, rótulo, [(valor, texto)])]
    pode_excluir = True
    descricao = ''
    url_sucesso = None  # nome de URL para redirecionar após salvar/excluir
    acoes_topo = []  # [(url_name, ícone, rótulo)] botões extras no topo da lista (ex.: importar)
    global_ = False  # tabela compartilhada entre clínicas (sem campo clinica)

    @classmethod
    def base_queryset(cls, request):
        return cls.model.objects.all() if cls.global_ else cls.model.objects.filter(clinica=request.clinica)

    @classmethod
    def antes_salvar(cls, request, obj, form):
        """Gancho opcional chamado antes de gravar (novo e edição)."""

    @classmethod
    def queryset(cls, request):
        qs = cls.base_queryset(request)
        if cls.ordenacao:
            qs = qs.order_by(*cls.ordenacao)
        return qs

    @classmethod
    def urls(cls, rota):
        prefixo = cls.url.split(':')[1]
        attrs = {'cfg': cls, 'modulo': cls.modulo}
        lista = type(f'{prefixo}Lista', (CrudLista,), attrs)
        novo = type(f'{prefixo}Novo', (CrudNovo,), attrs)
        editar = type(f'{prefixo}Editar', (CrudEditar,), attrs)
        excluir = type(f'{prefixo}Excluir', (CrudExcluir,), attrs)
        return [
            path(f'{rota}/', lista.as_view(), name=f'{prefixo}_list'),
            path(f'{rota}/novo/', novo.as_view(), name=f'{prefixo}_novo'),
            path(f'{rota}/<int:pk>/editar/', editar.as_view(), name=f'{prefixo}_editar'),
            path(f'{rota}/<int:pk>/excluir/', excluir.as_view(), name=f'{prefixo}_excluir'),
        ]


class CrudContextMixin:
    cfg = Crud

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['cfg'] = self.cfg
        ctx['url_list'] = f'{self.cfg.url}_list'
        ctx['url_novo'] = f'{self.cfg.url}_novo'
        ctx['url_editar'] = f'{self.cfg.url}_editar'
        ctx['url_excluir'] = f'{self.cfg.url}_excluir'
        ctx['pode_editar'] = tem_permissao(self.request, self.cfg.modulo, 'editar')
        return ctx


class CrudLista(AcessoMixin, CrudContextMixin, ListView):
    template_name = 'crud/list.html'
    paginate_by = 25

    def get_queryset(self):
        qs = self.cfg.queryset(self.request)
        q = self.request.GET.get('q', '').strip()
        if q and self.cfg.busca:
            cond = Q()
            for campo in self.cfg.busca:
                cond |= Q(**{f'{campo}__icontains': q})
            qs = qs.filter(cond)
        for campo, _, _ in self.cfg.filtros:
            v = self.request.GET.get(campo)
            if v not in (None, ''):
                if v in ('True', 'False'):
                    v = v == 'True'
                qs = qs.filter(**{campo: v})
        return qs.distinct() if self.cfg.busca else qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['cabecalhos'] = [c[1] for c in self.cfg.colunas]
        ctx['linhas'] = [
            (obj, [valor_coluna(obj, c[0], c[2] if len(c) > 2 else None) for c in self.cfg.colunas])
            for obj in ctx['object_list']
        ]
        ctx['q'] = self.request.GET.get('q', '')
        ctx['filtros'] = [(c, r, ops, self.request.GET.get(c, '')) for c, r, ops in self.cfg.filtros]
        params = self.request.GET.copy()
        params.pop('page', None)
        ctx['params'] = params.urlencode()
        return ctx


class CrudFormMixin(AcessoMixin, CrudContextMixin):
    template_name = 'crud/form.html'
    acao = 'editar'

    def get_form_class(self):
        return self.cfg.form_class

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw['clinica'] = self.request.clinica
        return kw

    def form_valid(self, form):
        obj = form.save(commit=False)
        if not obj.pk and not self.cfg.global_:
            obj.clinica = self.request.clinica
        self.antes_salvar(obj, form)
        obj.save()
        form.save_m2m()
        self.object = obj
        messages.success(self.request, f'{self.cfg.nome} salvo(a) com sucesso.')
        return redirect(self.get_success_url())

    def antes_salvar(self, obj, form):
        self.cfg.antes_salvar(self.request, obj, form)

    def get_success_url(self):
        prox = self.request.GET.get('next')
        if prox and prox.startswith('/'):
            return prox
        return reverse(self.cfg.url_sucesso or f'{self.cfg.url}_list')


class CrudNovo(CrudFormMixin, CreateView):
    def get_initial(self):
        init = super().get_initial()
        init.update({k: v for k, v in self.request.GET.items() if k not in ('next',)})
        return init


class CrudEditar(CrudFormMixin, UpdateView):
    def get_queryset(self):
        return self.cfg.base_queryset(self.request)


class CrudExcluir(AcessoMixin, View):
    acao = 'editar'
    cfg = Crud

    def post(self, request, pk):
        obj = get_object_or_404(self.cfg.base_queryset(request), pk=pk)
        try:
            obj.delete()
            messages.success(request, f'{self.cfg.nome} excluído(a).')
        except ProtectedError:
            messages.error(request, f'Não é possível excluir: {self.cfg.nome.lower()} possui registros vinculados. '
                                    'Inative-o(a) em vez de excluir.')
        return redirect(self.cfg.url_sucesso or f'{self.cfg.url}_list')
