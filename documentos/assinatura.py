"""Assinatura eletrônica de documentos com a imagem de assinatura do médico + verificação pública.

Fluxo (adaptado do controle PdfSign):
 1. O médico abre "Assinar documento", escolhe um PDF/imagem e posiciona a própria assinatura (somente a dele).
 2. Ao gerar, o servidor emite o código de verificação e a data/hora oficiais (não confia no relógio do navegador).
 3. O navegador monta o PDF certificado (carimbo + bloco Nome/CPF/data + faixa lateral com código) e envia.
 4. O servidor grava o PDF (armazenamento privado), o hash SHA-256 e, se informado, anexa ao prontuário.
 5. Qualquer pessoa confere em /documentos/verificar/ pelo código ou enviando o PDF (hash).

Importante: é assinatura eletrônica simples (Lei 14.063/2020, art. 4º, I). Para receitas de controle especial e
documentos que exigem assinatura qualificada, é necessário certificado ICP-Brasil.
"""
import hashlib
import mimetypes

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from cadastros.models import Medico, Paciente
from contas.permissoes import acesso, medico_do_usuario, tem_permissao

from .models import Documento, DocumentoAssinado, gerar_codigo, url_verificacao

SESSAO = 'assinatura_codigos'
VALIDADE_MIN = 30


def _ip(request):
    return (request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() or request.META.get('REMOTE_ADDR')
            or None)


def _medico_assinante(request):
    med = medico_do_usuario(request)
    if not med:
        return None, 'Seu usuário não está vinculado a um médico nesta clínica.'
    if not med.assinatura:
        return med, 'Cadastre a sua assinatura no cadastro do médico para assinar documentos.'
    return med, ''


# ------------------------------------------------------------------ imagem da assinatura
@acesso(None)
def imagem_assinatura(request, pk):
    """Só o próprio médico (para assinar) ou quem edita cadastros (pré-visualização) pode ver."""
    med = get_object_or_404(Medico, pk=pk, clinica=request.clinica)
    if not (med.usuario_id == request.user.pk or tem_permissao(request, 'cadastros', 'editar')):
        raise PermissionDenied
    if not med.assinatura:
        raise Http404
    tipo = mimetypes.guess_type(med.assinatura.name)[0] or 'image/png'
    resp = FileResponse(med.assinatura.open('rb'), content_type=tipo)
    resp['Cache-Control'] = 'private, no-store'
    return resp


# ------------------------------------------------------------------ tela de assinatura
@acesso('documentos', 'editar')
def assinar(request):
    med, erro = _medico_assinante(request)
    if erro:
        messages.warning(request, erro)
    return render(request, 'documentos/assinar.html', {
        'med': med if not erro else None, 'erro': erro, 'url_verificacao': url_verificacao(),
        'paciente_ini': Paciente.objects.filter(clinica=request.clinica, pk=request.GET.get('paciente') or 0).first()})


@acesso('documentos', 'editar')
@require_POST
def iniciar(request):
    """Emite código de verificação e data/hora oficiais para uma assinatura."""
    med, erro = _medico_assinante(request)
    if erro:
        return JsonResponse({'ok': False, 'erro': erro}, status=403)
    agora = timezone.localtime()
    codigo = gerar_codigo()
    while DocumentoAssinado.objects.filter(codigo=codigo).exists() or \
            Documento.objects.filter(codigo_verificacao=codigo).exists():
        codigo = gerar_codigo()
    pendentes = request.session.get(SESSAO, {})
    limite = (timezone.now() - timezone.timedelta(minutes=VALIDADE_MIN)).timestamp()
    pendentes = {c: v for c, v in pendentes.items() if v['t'] > limite}
    pendentes[codigo] = {'t': timezone.now().timestamp(), 'em': agora.isoformat(), 'medico': med.pk}
    request.session[SESSAO] = pendentes
    return JsonResponse({'ok': True, 'codigo': codigo, 'data': agora.strftime('%d/%m/%Y'),
                         'hora': agora.strftime('%H:%M:%S'), 'url': url_verificacao(),
                         'nome': med.nome, 'cpf': med.cpf, 'registro': med.registro_completo})


@acesso('documentos', 'editar')
@require_POST
def gravar(request):
    med, erro = _medico_assinante(request)
    if erro:
        return JsonResponse({'ok': False, 'erro': erro}, status=403)
    codigo = request.POST.get('codigo', '')
    pend = request.session.get(SESSAO, {}).get(codigo)
    if not pend or pend['medico'] != med.pk:
        return JsonResponse({'ok': False, 'erro': 'Código de verificação inválido ou expirado. Gere novamente.'},
                            status=400)
    pdf = request.FILES.get('pdf')
    if not pdf or pdf.size > 50 * 1024 * 1024:
        return JsonResponse({'ok': False, 'erro': 'PDF assinado não recebido (ou maior que 50 MB).'}, status=400)
    conteudo = pdf.read()
    if not conteudo.startswith(b'%PDF'):
        return JsonResponse({'ok': False, 'erro': 'Arquivo enviado não é um PDF.'}, status=400)
    paciente = Paciente.objects.filter(clinica=request.clinica, pk=request.POST.get('paciente') or 0).first()
    nome = (request.POST.get('nome_arquivo') or 'documento')[:150]
    base = nome.rsplit('.', 1)[0]
    doc = DocumentoAssinado(
        clinica=request.clinica, medico=med, paciente=paciente, nome_arquivo=nome, codigo=codigo,
        sha256=hashlib.sha256(conteudo).hexdigest(), sha256_original=request.POST.get('sha256_original', '')[:64],
        paginas=int(request.POST.get('paginas') or 1), usuario=request.user, ip=_ip(request),
        assinado_em=timezone.datetime.fromisoformat(pend['em']))
    doc.arquivo.save(f'{base}_assinado_{codigo}.pdf', ContentFile(conteudo), save=False)
    doc.save()
    if paciente and request.POST.get('anexar') == '1' and tem_permissao(request, 'prontuario', 'editar'):
        from prontuario.models import Anexo
        from prontuario.views import registrar
        anx = Anexo(clinica=request.clinica, paciente=paciente, tipo='assinado', titulo=f'{base} (assinado)',
                    resultado=f'Assinado eletronicamente por {med.nome} em '
                              f'{timezone.localtime(doc.assinado_em):%d/%m/%Y %H:%M}. Código {codigo}.',
                    enviado_por=request.user)
        anx.arquivo.save(f'{base}_assinado_{codigo}.pdf', ContentFile(conteudo), save=False)
        anx.save()
        doc.anexo = anx
        doc.save(update_fields=['anexo'])
        registrar(request, paciente, f'Documento assinado anexado: {base}')
    pendentes = request.session.get(SESSAO, {})
    pendentes.pop(codigo, None)
    request.session[SESSAO] = pendentes
    return JsonResponse({'ok': True, 'id': doc.pk, 'codigo': codigo, 'anexado': bool(doc.anexo_id)})


@acesso('documentos')
def assinados(request):
    from django.core.paginator import Paginator
    from django.db.models import Q
    qs = DocumentoAssinado.objects.filter(clinica=request.clinica).select_related('medico', 'paciente')
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(Q(nome_arquivo__icontains=q) | Q(codigo__icontains=q) | Q(paciente__nome__icontains=q) |
                       Q(medico__nome__icontains=q))
    pagina = Paginator(qs, 25).get_page(request.GET.get('page'))
    return render(request, 'documentos/assinados.html', {'pagina': pagina, 'q': q,
                                                         'pode_assinar': tem_permissao(request, 'documentos', 'editar')})


@acesso('documentos')
def arquivo_assinado(request, pk):
    d = get_object_or_404(DocumentoAssinado, pk=pk, clinica=request.clinica)
    resp = FileResponse(d.arquivo.open('rb'), content_type='application/pdf')
    resp['Content-Disposition'] = f'inline; filename="{d.arquivo.name.split("/")[-1]}"'
    resp['Cache-Control'] = 'private, no-store'
    return resp


# ------------------------------------------------------------------ verificação pública
def verificar(request):
    codigo = (request.POST.get('codigo') or request.GET.get('codigo') or '').strip().upper()
    resultado, hash_ok = None, None
    if codigo:
        a = DocumentoAssinado.objects.select_related('medico', 'clinica').filter(codigo=codigo).first()
        if a:
            a.clinica.ativar_fuso()
            resultado = {'tipo': 'PDF assinado eletronicamente', 'documento': a.nome_arquivo, 'medico': a.medico,
                         'clinica': a.clinica, 'data': a.assinado_em, 'paginas': a.paginas, 'sha256': a.sha256}
        else:
            from prontuario.models import TermoAssinado
            t = TermoAssinado.objects.select_related('clinica', 'medico').filter(codigo_verificacao=codigo).first()
            if t:
                t.clinica.ativar_fuso()
                resultado = {'tipo': 'Termo assinado pelo paciente na tela', 'documento': t.titulo,
                             'medico': t.medico or type('M', (), {'nome': t.assinante_nome, 'registro_completo': ''})(),
                             'clinica': t.clinica, 'data': t.assinado_em,
                             'paciente_iniciais': ''.join(x[0] for x in t.assinante_nome.split() if x)[:6].upper()}
        if not resultado:
            d = Documento.objects.select_related('medico', 'clinica', 'paciente').filter(
                codigo_verificacao=codigo).first()
            if d:
                d.clinica.ativar_fuso()
                resultado = {'tipo': d.titulo_exibicao, 'documento': d.titulo_exibicao, 'medico': d.medico,
                             'clinica': d.clinica, 'data': d.data,
                             'paciente_iniciais': ''.join(p[0] for p in d.paciente.nome.split() if p)[:6].upper()}
        arq = request.FILES.get('arquivo')
        if resultado and arq and resultado.get('sha256'):
            hash_ok = hashlib.sha256(arq.read()).hexdigest() == resultado['sha256']
    return render(request, 'documentos/verificar.html', {'codigo': codigo, 'r': resultado, 'hash_ok': hash_ok,
                                                         'buscou': bool(codigo)})
