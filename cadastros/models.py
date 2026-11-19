import datetime

from django.conf import settings
from django.db import models

from contas.models import ClinicaModel

UFS = [(u, u) for u in 'AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split()]


class Especialidade(ClinicaModel):
    nome = models.CharField(max_length=100)
    descricao = models.CharField('Descrição', max_length=250, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome


class Medico(ClinicaModel):
    nome = models.CharField(max_length=150)
    conselho = models.CharField('Conselho', max_length=10, default='CRM')
    registro = models.CharField('Nº registro', max_length=20, blank=True)
    uf_registro = models.CharField('UF', max_length=2, choices=UFS, blank=True)
    especialidades = models.ManyToManyField(Especialidade, blank=True, related_name='medicos')
    celular = models.CharField('Celular / WhatsApp', max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name='medicos', verbose_name='Usuário do sistema',
                                help_text='Vincule para o médico acessar a própria agenda e receber lembretes.')
    ACESSO_PRONTUARIO = [('nenhum', 'Não acessa o prontuário'), ('consulta', 'Somente consulta (leitura)'),
                         ('completo', 'Consulta e registro de atendimentos')]
    acesso_prontuario = models.CharField(
        'Acesso ao prontuário', max_length=10, choices=ACESSO_PRONTUARIO, default='consulta',
        help_text='Define se o médico, ao entrar no sistema, pode ver o prontuário e se pode registrar dados. '
                  'Prevalece sobre o perfil de acesso do usuário vinculado.')
    percentual_repasse = models.DecimalField('Repasse ao profissional (%)', max_digits=5, decimal_places=2,
                                             default=0, help_text='Percentual sobre o valor líquido recebido.')
    agenda_online = models.BooleanField('Aparece no agendamento online', default=True)
    cor = models.CharField('Cor na agenda', max_length=7, default='#2bb59a')
    receber_agenda_diaria = models.BooleanField('Receber resumo diário da agenda', default=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Médico / Profissional'

    def __str__(self):
        return self.nome

    @property
    def registro_completo(self):
        if not self.registro:
            return ''
        return f'{self.conselho} {self.registro}{"/" + self.uf_registro if self.uf_registro else ""}'


class Paciente(ClinicaModel):
    SEXO = [('F', 'Feminino'), ('M', 'Masculino'), ('O', 'Outro')]
    nome = models.CharField(max_length=150)
    cpf = models.CharField('CPF', max_length=14, blank=True)
    rg = models.CharField('RG', max_length=20, blank=True)
    data_nascimento = models.DateField('Nascimento', null=True, blank=True)
    sexo = models.CharField(max_length=1, choices=SEXO, blank=True)
    celular = models.CharField('Celular / WhatsApp', max_length=20, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    email = models.EmailField('E-mail', blank=True)
    cep = models.CharField('CEP', max_length=9, blank=True)
    endereco = models.CharField('Endereço', max_length=200, blank=True)
    numero = models.CharField('Nº', max_length=10, blank=True)
    bairro = models.CharField(max_length=100, blank=True)
    cidade = models.CharField(max_length=100, blank=True)
    uf = models.CharField('UF', max_length=2, choices=UFS, blank=True)
    convenio = models.CharField('Convênio', max_length=100, blank=True)
    carteirinha = models.CharField('Nº carteirinha', max_length=50, blank=True)
    responsavel = models.CharField('Responsável', max_length=150, blank=True)
    alergias = models.TextField(blank=True)
    observacoes = models.TextField('Observações', blank=True)
    ORIGENS = [('', '-'), ('indicacao', 'Indicação'), ('instagram', 'Instagram'), ('google', 'Google'),
               ('facebook', 'Facebook'), ('site', 'Site'), ('convenio', 'Convênio'), ('online', 'Agendamento online'),
               ('outro', 'Outro')]
    origem = models.CharField('Como conheceu a clínica', max_length=15, choices=ORIGENS, blank=True)
    aceita_whatsapp = models.BooleanField('Aceita receber WhatsApp', default=True)
    aceita_email = models.BooleanField('Aceita receber e-mail', default=True)
    aceita_sms = models.BooleanField('Aceita receber SMS', default=True)
    aceita_campanhas = models.BooleanField('Aceita receber campanhas', default=True)
    consentimento_lgpd_em = models.DateTimeField('Consentimento LGPD em', null=True, blank=True, editable=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return self.nome

    @property
    def idade(self):
        if not self.data_nascimento:
            return None
        hoje = datetime.date.today()
        n = self.data_nascimento
        return hoje.year - n.year - ((hoje.month, hoje.day) < (n.month, n.day))


class Medicamento(ClinicaModel):
    ORIGENS = [('manual', 'Cadastro manual'), ('cmed', 'Tabela CMED / ANVISA')]
    nome = models.CharField('Produto / nome comercial', max_length=200)
    principio_ativo = models.CharField('Princípio ativo (substância)', max_length=500, blank=True)
    apresentacao = models.CharField('Apresentação', max_length=300, blank=True, help_text='Ex.: 500 MG COM CT BL X 20')
    laboratorio = models.CharField('Laboratório', max_length=200, blank=True)
    cnpj_laboratorio = models.CharField('CNPJ do laboratório', max_length=20, blank=True)
    registro_anvisa = models.CharField('Registro ANVISA', max_length=20, blank=True, db_index=True)
    codigo_ggrem = models.CharField('Código GGREM', max_length=20, blank=True, db_index=True)
    ean = models.CharField('EAN (código de barras)', max_length=20, blank=True, db_index=True)
    classe_terapeutica = models.CharField('Classe terapêutica', max_length=200, blank=True)
    tipo_produto = models.CharField('Tipo de produto', max_length=60, blank=True,
                                    help_text='Genérico, Similar, Novo, Referência...')
    tarja = models.CharField(max_length=60, blank=True)
    regime_preco = models.CharField('Regime de preço', max_length=30, blank=True)
    preco_fabrica = models.DecimalField('Preço fábrica - PF (R$)', max_digits=12, decimal_places=2, null=True,
                                        blank=True)
    preco_maximo_consumidor = models.DecimalField('Preço máximo ao consumidor - PMC (R$)', max_digits=12,
                                                  decimal_places=2, null=True, blank=True)
    aliquota_icms = models.CharField('Alíquota ICMS dos preços', max_length=10, blank=True)
    restricao_hospitalar = models.BooleanField('Restrição hospitalar', default=False)
    via = models.CharField('Via de administração', max_length=50, blank=True, default='Oral')
    posologia_padrao = models.CharField('Posologia padrão', max_length=250, blank=True)
    controlado = models.BooleanField('Controlado (receita especial)', default=False)
    origem = models.CharField(max_length=10, choices=ORIGENS, default='manual')
    atualizado_tabela_em = models.DateField('Atualizado pela tabela em', null=True, blank=True, editable=False)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']

    def __str__(self):
        return f'{self.nome} {self.apresentacao}'.strip()[:200]

    @property
    def bula_url(self):
        """Consulta da bula no Bulário Eletrônico da ANVISA."""
        from urllib.parse import quote
        return f'https://consultas.anvisa.gov.br/#/bulario/q/?nomeProduto={quote(self.nome)}'


class InteracaoMedicamentosa(models.Model):
    """Base de interações medicamentosas (compartilhada). Substâncias em texto livre, comparadas sem acento."""
    GRAVIDADE = [('contraindicada', 'Contraindicada'), ('grave', 'Grave'), ('moderada', 'Moderada'),
                 ('leve', 'Leve')]
    substancia_a = models.CharField('Substância / classe A', max_length=600,
                                    help_text='Use termos do princípio ativo. Vários termos separados por vírgula.')
    substancia_b = models.CharField('Substância / classe B', max_length=600)
    gravidade = models.CharField(max_length=15, choices=GRAVIDADE, default='moderada')
    efeito = models.TextField('Efeito / risco')
    conduta = models.TextField('Conduta sugerida', blank=True)
    fonte = models.CharField(max_length=200, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['substancia_a', 'substancia_b']
        verbose_name = 'Interação medicamentosa'
        verbose_name_plural = 'Interações medicamentosas'

    def __str__(self):
        return f'{self.substancia_a} x {self.substancia_b} ({self.get_gravidade_display()})'

    @staticmethod
    def termos(txt):
        import unicodedata
        txt = unicodedata.normalize('NFKD', txt or '').encode('ascii', 'ignore').decode().lower()
        return [t.strip() for t in txt.split(',') if t.strip()]


class HorarioAtendimento(ClinicaModel):
    """Grade de horários do profissional (usada no agendamento online e na taxa de ocupação)."""
    DIAS = [(0, 'Segunda'), (1, 'Terça'), (2, 'Quarta'), (3, 'Quinta'), (4, 'Sexta'), (5, 'Sábado'), (6, 'Domingo')]
    medico = models.ForeignKey(Medico, on_delete=models.CASCADE, related_name='horarios',
                               verbose_name='Profissional')
    dia_semana = models.PositiveSmallIntegerField('Dia da semana', choices=DIAS)
    inicio = models.TimeField('Das')
    fim = models.TimeField('Até')

    class Meta:
        ordering = ['medico', 'dia_semana', 'inicio']
        verbose_name = 'Horário de atendimento'

    def __str__(self):
        return f'{self.medico} - {self.get_dia_semana_display()} {self.inicio:%H:%M}-{self.fim:%H:%M}'

    @property
    def minutos(self):
        return (self.fim.hour * 60 + self.fim.minute) - (self.inicio.hour * 60 + self.inicio.minute)


class Cid(models.Model):
    """CID-10 / CID-11 (tabela de referência compartilhada por todas as clínicas)."""
    VERSOES = [('10', 'CID-10'), ('11', 'CID-11')]
    versao = models.CharField('Versão', max_length=2, choices=VERSOES, default='10')
    codigo = models.CharField('Código', max_length=20)
    nome = models.CharField('Descrição', max_length=300)
    categoria = models.CharField(max_length=3, blank=True, db_index=True)
    sexo = models.CharField('Restrição de sexo', max_length=1, blank=True, help_text='M, F ou vazio')
    subcategoria = models.BooleanField(default=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['versao', 'codigo']
        unique_together = ('versao', 'codigo')
        verbose_name = 'CID'
        verbose_name_plural = 'CID-10 / CID-11'

    def __str__(self):
        pre = 'CID-11 ' if self.versao == '11' else ''
        return f'{pre}{self.codigo} - {self.nome}'


class Procedimento(ClinicaModel):
    """Tabela de procedimentos (SUS/SIGTAP, TUSS ou próprios da clínica)."""
    ORIGENS = [('sus', 'SUS - SIGTAP'), ('tuss', 'TUSS / CBHPM'), ('propria', 'Própria da clínica')]
    COMPLEXIDADE = [('0', 'Não se aplica'), ('1', 'Atenção básica'), ('2', 'Média complexidade'),
                    ('3', 'Alta complexidade')]
    codigo = models.CharField('Código', max_length=20, db_index=True)
    nome = models.CharField('Procedimento', max_length=300)
    origem = models.CharField(max_length=10, choices=ORIGENS, default='propria')
    complexidade = models.CharField(max_length=1, choices=COMPLEXIDADE, blank=True)
    sexo = models.CharField('Sexo permitido', max_length=1, blank=True, help_text='M, F, I (indiferente)')
    idade_minima = models.PositiveIntegerField('Idade mínima (meses)', null=True, blank=True)
    idade_maxima = models.PositiveIntegerField('Idade máxima (meses)', null=True, blank=True)
    valor_sh = models.DecimalField('Valor SUS - serviço hospitalar (R$)', max_digits=12, decimal_places=2,
                                   default=0)
    valor_sa = models.DecimalField('Valor SUS - ambulatorial (R$)', max_digits=12, decimal_places=2, default=0)
    valor_sp = models.DecimalField('Valor SUS - profissional (R$)', max_digits=12, decimal_places=2, default=0)
    valor_particular = models.DecimalField('Valor particular (R$)', max_digits=12, decimal_places=2, null=True,
                                           blank=True)
    competencia = models.CharField('Competência', max_length=7, blank=True, help_text='AAAAMM da tabela SIGTAP')
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['codigo']
        unique_together = ('clinica', 'origem', 'codigo')

    def __str__(self):
        return f'{self.codigo_formatado} - {self.nome}'[:200]

    @property
    def codigo_formatado(self):
        c = self.codigo
        if self.origem == 'sus' and len(c) == 10:
            return f'{c[:2]}.{c[2:4]}.{c[4:6]}.{c[6:9]}-{c[9]}'
        return c

    @property
    def valor_sus_total(self):
        return (self.valor_sh or 0) + (self.valor_sa or 0) + (self.valor_sp or 0)


class TipoAtendimento(ClinicaModel):
    """Tabela de preços dos tipos de atendimento."""
    nome = models.CharField(max_length=120)
    especialidade = models.ForeignKey(Especialidade, on_delete=models.SET_NULL, null=True, blank=True)
    procedimento = models.ForeignKey('Procedimento', on_delete=models.SET_NULL, null=True, blank=True,
                                     verbose_name='Procedimento (SUS/TUSS)')
    duracao_minutos = models.PositiveIntegerField('Duração (min)', default=30)
    valor = models.DecimalField('Valor particular (R$)', max_digits=10, decimal_places=2, default=0)
    valor_convenio = models.DecimalField('Valor convênio (R$)', max_digits=10, decimal_places=2, null=True,
                                         blank=True)
    valor_sessao_pacote = models.DecimalField('Valor por sessão em pacote (R$)', max_digits=10, decimal_places=2,
                                              null=True, blank=True)
    permite_pacote = models.BooleanField('Permite venda em pacote de sessões', default=False)
    agendamento_online = models.BooleanField('Disponível no agendamento online', default=False)
    teleconsulta = models.BooleanField('É teleconsulta (gera sala de vídeo)', default=False)
    retorno_dias = models.PositiveIntegerField('Retorno sugerido (dias)', null=True, blank=True)
    ativo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'Tipo de atendimento'

    def __str__(self):
        return self.nome
