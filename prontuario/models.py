"""Prontuário eletrônico do paciente (PEP)."""
from decimal import Decimal

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone

from cadastros.models import Cid, Medico, Paciente
from contas.models import Clinica, ClinicaModel

# Arquivos do prontuário ficam fora de /media (não são públicos); o download passa por verificação de permissão.
armazenamento_privado = FileSystemStorage(location=settings.BASE_DIR / 'privado')

SIM_NAO_EX = [('', '-'), ('nunca', 'Nunca'), ('ex', 'Ex-usuário'), ('ocasional', 'Ocasional'), ('atual', 'Atual')]


class HistoricoClinico(ClinicaModel):
    """Anamnese geral / antecedentes - um por paciente, atualizado ao longo do tempo."""
    TIPOS_SANGUE = [('', '-')] + [(t, t) for t in ('A+', 'A-', 'B+', 'B-', 'AB+', 'AB-', 'O+', 'O-')]
    paciente = models.OneToOneField(Paciente, on_delete=models.CASCADE, related_name='historico')
    tipo_sanguineo = models.CharField('Tipo sanguíneo', max_length=3, choices=TIPOS_SANGUE, blank=True)
    alergias = models.TextField('Alergias', blank=True)
    doencas_cronicas = models.TextField('Doenças crônicas / comorbidades', blank=True)
    medicamentos_uso = models.TextField('Medicamentos em uso contínuo', blank=True)
    antecedentes_pessoais = models.TextField('Antecedentes pessoais', blank=True)
    cirurgias = models.TextField('Cirurgias prévias', blank=True)
    internacoes = models.TextField('Internações', blank=True)
    antecedentes_familiares = models.TextField('Antecedentes familiares', blank=True)
    tabagismo = models.CharField(max_length=10, choices=SIM_NAO_EX, blank=True)
    etilismo = models.CharField(max_length=10, choices=SIM_NAO_EX, blank=True)
    drogas = models.CharField('Outras drogas', max_length=10, choices=SIM_NAO_EX, blank=True)
    atividade_fisica = models.CharField('Atividade física', max_length=200, blank=True)
    alimentacao = models.CharField('Alimentação', max_length=200, blank=True)
    sono = models.CharField(max_length=200, blank=True)
    gineco_obstetrico = models.TextField('Gineco-obstétrico (DUM, G/P/A, método contraceptivo)', blank=True)
    vacinacao = models.TextField('Vacinação', blank=True)
    observacoes = models.TextField('Observações', blank=True)
    atualizado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                       blank=True, related_name='+', editable=False)

    class Meta:
        verbose_name = 'Histórico clínico'

    def __str__(self):
        return f'Histórico de {self.paciente}'


class ModeloProntuario(ClinicaModel):
    """Modelo de prontuário por especialidade: campos extras + textos padrão.

    Definição dos campos: uma linha por campo no formato
        Seção | Rótulo | tipo | opções
    Seção: S, O, A ou P. Tipos: texto, texto_longo, numero, sim_nao, opcoes (opções separadas por ;), escala (0-10).
    """
    TIPOS_CAMPO = ('texto', 'texto_longo', 'numero', 'sim_nao', 'opcoes', 'escala')
    nome = models.CharField(max_length=120)
    especialidade = models.ForeignKey('cadastros.Especialidade', on_delete=models.SET_NULL, null=True, blank=True,
                                      help_text='Usado automaticamente pelos médicos desta especialidade.')
    definicao = models.TextField('Campos do modelo', blank=True,
                                 help_text='Uma linha por campo: Seção | Rótulo | tipo | opções. '
                                           'Ex.: O | Força muscular (MRC) | opcoes | 0;1;2;3;4;5')
    queixa_padrao = models.TextField('Texto padrão - queixa/HDA', blank=True)
    exame_fisico_padrao = models.TextField('Texto padrão - exame físico', blank=True)
    conduta_padrao = models.TextField('Texto padrão - conduta', blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Modelo de prontuário'
        verbose_name_plural = 'Modelos de prontuário'

    def __str__(self):
        return self.nome

    def campos(self):
        lista = []
        for i, linha in enumerate(self.definicao.splitlines()):
            partes = [p.strip() for p in linha.split('|')]
            if len(partes) < 2 or not partes[1]:
                continue
            secao = partes[0].upper()[:1] if partes[0] else 'O'
            tipo = partes[2].lower() if len(partes) > 2 and partes[2].lower() in self.TIPOS_CAMPO else 'texto'
            opcoes = [o.strip() for o in partes[3].split(';') if o.strip()] if len(partes) > 3 else []
            lista.append({'chave': f'c{i}', 'secao': secao if secao in 'SOAP' else 'O', 'rotulo': partes[1],
                          'tipo': tipo, 'opcoes': opcoes})
        return lista


class Atendimento(ClinicaModel):
    """Registro de atendimento / evolução clínica (modelo SOAP)."""
    TIPOS = [('consulta', 'Consulta'), ('retorno', 'Retorno'), ('sessao', 'Sessão / evolução'),
             ('procedimento', 'Procedimento'), ('urgencia', 'Urgência'), ('teleconsulta', 'Teleconsulta'),
             ('outro', 'Outro')]
    STATUS = [('aberto', 'Em andamento'), ('finalizado', 'Finalizado (assinado)')]

    paciente = models.ForeignKey(Paciente, on_delete=models.PROTECT, related_name='atendimentos')
    medico = models.ForeignKey(Medico, on_delete=models.PROTECT, related_name='atendimentos',
                               verbose_name='Profissional')
    agendamento = models.ForeignKey('agenda.Agendamento', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='atendimentos', editable=False)
    data = models.DateTimeField('Data/hora', default=timezone.now)
    tipo = models.CharField(max_length=15, choices=TIPOS, default='consulta')
    # S - subjetivo
    queixa_principal = models.TextField('Queixa principal', blank=True)
    hda = models.TextField('História da doença atual (HDA)', blank=True)
    revisao_sistemas = models.TextField('Revisão de sistemas / interrogatório', blank=True)
    # O - objetivo
    pa_sistolica = models.PositiveSmallIntegerField('PA sistólica (mmHg)', null=True, blank=True)
    pa_diastolica = models.PositiveSmallIntegerField('PA diastólica (mmHg)', null=True, blank=True)
    fc = models.PositiveSmallIntegerField('FC (bpm)', null=True, blank=True)
    fr = models.PositiveSmallIntegerField('FR (irpm)', null=True, blank=True)
    temperatura = models.DecimalField('Temperatura (°C)', max_digits=4, decimal_places=1, null=True, blank=True)
    spo2 = models.PositiveSmallIntegerField('SpO₂ (%)', null=True, blank=True)
    peso = models.DecimalField('Peso (kg)', max_digits=5, decimal_places=2, null=True, blank=True)
    altura = models.PositiveSmallIntegerField('Altura (cm)', null=True, blank=True)
    glicemia = models.PositiveSmallIntegerField('Glicemia capilar (mg/dL)', null=True, blank=True)
    dor = models.PositiveSmallIntegerField('Escala de dor (0-10)', null=True, blank=True,
                                           choices=[(i, str(i)) for i in range(11)])
    exame_fisico = models.TextField('Exame físico', blank=True)
    # A - avaliação
    cid_principal = models.ForeignKey(Cid, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                      verbose_name='CID principal')
    cids_secundarios = models.ManyToManyField(Cid, blank=True, related_name='+', verbose_name='CIDs secundários')
    hipotese_diagnostica = models.TextField('Avaliação / hipótese diagnóstica', blank=True)
    # P - plano
    conduta = models.TextField('Conduta / plano terapêutico', blank=True)
    exames_solicitados = models.TextField('Exames solicitados', blank=True)
    orientacoes = models.TextField('Orientações ao paciente', blank=True)
    retorno_em = models.DateField('Retorno sugerido em', null=True, blank=True)
    anotacoes_privadas = models.TextField('Anotações privadas do profissional', blank=True,
                                          help_text='Visíveis apenas para o autor do atendimento.')

    modelo = models.ForeignKey(ModeloProntuario, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name='Modelo de prontuário')
    respostas = models.JSONField(default=dict, blank=True, editable=False)

    status = models.CharField(max_length=12, choices=STATUS, default='aberto', editable=False)
    finalizado_em = models.DateTimeField(null=True, blank=True, editable=False)
    criado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+', editable=False)

    class Meta:
        ordering = ['-data']
        verbose_name = 'Atendimento (evolução)'

    def __str__(self):
        return f'{self.get_tipo_display()} {timezone.localtime(self.data):%d/%m/%Y %H:%M} - {self.paciente}'

    @property
    def finalizado(self):
        return self.status == 'finalizado'

    @property
    def imc(self):
        if self.peso and self.altura:
            m = Decimal(self.altura) / 100
            return (self.peso / (m * m)).quantize(Decimal('0.1'))
        return None

    @property
    def imc_classe(self):
        i = self.imc
        if i is None:
            return ''
        for limite, nome in ((Decimal('18.5'), 'Baixo peso'), (Decimal('25'), 'Eutrófico'),
                             (Decimal('30'), 'Sobrepeso'), (Decimal('35'), 'Obesidade I'),
                             (Decimal('40'), 'Obesidade II')):
            if i < limite:
                return nome
        return 'Obesidade III'

    @property
    def pa(self):
        if self.pa_sistolica and self.pa_diastolica:
            return f'{self.pa_sistolica}x{self.pa_diastolica}'
        return ''

    @property
    def tem_sinais_vitais(self):
        return any([self.pa, self.fc, self.fr, self.temperatura, self.spo2, self.peso, self.altura, self.glicemia,
                    self.dor is not None])

    def respostas_por_secao(self):
        """{'S': [(rótulo, valor)], ...} a partir do snapshot salvo."""
        saida = {}
        for item in (self.respostas or {}).get('campos', []):
            if item.get('valor') not in (None, ''):
                saida.setdefault(item['secao'], []).append((item['rotulo'], item['valor']))
        return saida

    def pode_editar(self, user):
        if self.finalizado:
            return False
        return user.is_superuser or (self.medico.usuario_id == user.pk) or self.criado_por_id == user.pk


class Adendo(models.Model):
    """Complemento a um atendimento já finalizado (o registro original não é alterado)."""
    atendimento = models.ForeignKey(Atendimento, on_delete=models.CASCADE, related_name='adendos')
    texto = models.TextField()
    autor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['criado_em']


class Anexo(ClinicaModel):
    TIPOS = [('laboratorio', 'Exame laboratorial'), ('imagem', 'Exame de imagem'), ('laudo', 'Laudo externo'),
             ('foto', 'Foto clínica'), ('termo', 'Termo de consentimento'), ('receita', 'Receita externa'),
             ('video', 'Gravação de teleconsulta'), ('outro', 'Outro')]
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='anexos')
    atendimento = models.ForeignKey(Atendimento, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='anexos')
    tipo = models.CharField(max_length=15, choices=TIPOS, default='laboratorio')
    titulo = models.CharField('Título', max_length=150)
    data = models.DateField('Data do exame/documento', default=timezone.localdate)
    arquivo = models.FileField(upload_to='prontuario/%Y/%m/', storage=armazenamento_privado, blank=True)
    resultado = models.TextField('Resultado / descrição', blank=True)
    enviado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='+', editable=False)

    class Meta:
        ordering = ['-data', '-id']
        verbose_name = 'Exame / anexo'

    def __str__(self):
        return self.titulo

    @property
    def nome_arquivo(self):
        return self.arquivo.name.split('/')[-1] if self.arquivo else ''

    @property
    def eh_imagem(self):
        return self.nome_arquivo.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp'))

    @property
    def eh_video(self):
        return self.nome_arquivo.lower().endswith(('.webm', '.mp4'))


class ExameLaboratorial(ClinicaModel):
    """Catálogo de exames com unidade e faixa de referência (para o comparativo)."""
    nome = models.CharField(max_length=120)
    unidade = models.CharField(max_length=30, blank=True)
    ref_min = models.DecimalField('Referência mínima', max_digits=12, decimal_places=3, null=True, blank=True)
    ref_max = models.DecimalField('Referência máxima', max_digits=12, decimal_places=3, null=True, blank=True)
    grupo = models.CharField(max_length=60, blank=True, help_text='Ex.: Hemograma, Lipidograma, Função renal')
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['grupo', 'nome']
        verbose_name = 'Exame laboratorial'
        verbose_name_plural = 'Exames laboratoriais (catálogo)'

    def __str__(self):
        return f'{self.nome} ({self.unidade})' if self.unidade else self.nome

    @staticmethod
    def fmt(v):
        s = f'{v:f}'
        s = s.rstrip('0').rstrip('.') if '.' in s else s
        return s.replace('.', ',')

    @property
    def referencia(self):
        if self.ref_min is not None and self.ref_max is not None:
            return f'{self.fmt(self.ref_min)} - {self.fmt(self.ref_max)}'
        if self.ref_max is not None:
            return f'< {self.fmt(self.ref_max)}'
        if self.ref_min is not None:
            return f'> {self.fmt(self.ref_min)}'
        return ''


class ResultadoExame(ClinicaModel):
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='resultados_exames')
    exame = models.ForeignKey(ExameLaboratorial, on_delete=models.PROTECT, related_name='resultados')
    data = models.DateField('Data da coleta', default=timezone.localdate)
    valor = models.DecimalField(max_digits=12, decimal_places=3)
    anexo = models.ForeignKey(Anexo, on_delete=models.SET_NULL, null=True, blank=True, related_name='resultados')
    observacao = models.CharField('Observação', max_length=200, blank=True)
    lancado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                    related_name='+', editable=False)

    class Meta:
        ordering = ['exame__nome', 'data']
        verbose_name = 'Resultado de exame'

    @property
    def valor_fmt(self):
        return ExameLaboratorial.fmt(self.valor)

    @property
    def situacao(self):
        e = self.exame
        if e.ref_min is not None and self.valor < e.ref_min:
            return 'baixo'
        if e.ref_max is not None and self.valor > e.ref_max:
            return 'alto'
        return 'normal'


class AcessoProntuario(models.Model):
    """Trilha de auditoria (LGPD / CFM): quem acessou ou alterou cada prontuário."""
    clinica = models.ForeignKey(Clinica, on_delete=models.CASCADE, related_name='+')
    paciente = models.ForeignKey(Paciente, on_delete=models.CASCADE, related_name='acessos_prontuario')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    acao = models.CharField(max_length=60)
    data = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ['-data']
