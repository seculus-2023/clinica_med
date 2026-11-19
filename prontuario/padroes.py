"""Modelos de prontuário por especialidade e catálogo de exames laboratoriais padrão."""
from decimal import Decimal

from cadastros.models import Especialidade

from .models import ExameLaboratorial, ModeloProntuario

MODELOS = {
    'Clínica geral': {
        'nome': 'Clínica geral - consulta',
        'definicao': """S | Tempo de evolução dos sintomas | texto
S | Febre | sim_nao
S | Uso de medicamentos recentes | texto
O | Estado geral | opcoes | BEG;REG;MEG
O | Hidratação | opcoes | Hidratado;Desidratado +/4+;Desidratado ++/4+;Desidratado +++/4+
A | Risco cardiovascular | opcoes | Baixo;Intermediário;Alto
P | Encaminhamento | texto""",
        'exame': 'BEG, LOTE, corado, hidratado, anictérico, acianótico, afebril.\nACV: RCR 2T, BNF, sem sopros.\n'
                 'AR: MV+ bilateralmente, sem ruídos adventícios.\nABD: plano, flácido, indolor, RHA+, sem VMG.\n'
                 'MMII: sem edema, panturrilhas livres.',
    },
    'Cardiologia': {
        'nome': 'Cardiologia - avaliação',
        'definicao': """S | Dor torácica | opcoes | Ausente;Típica;Atípica;Não anginosa
S | Dispneia (NYHA) | opcoes | I;II;III;IV
S | Palpitações | sim_nao
S | Síncope / pré-síncope | sim_nao
O | Ritmo | opcoes | Regular;Irregular
O | Sopro | texto
O | Edema de MMII | opcoes | Ausente;+/4+;++/4+;+++/4+;++++/4+
A | ECG | texto_longo
A | Risco cardiovascular (escore) | opcoes | Baixo;Intermediário;Alto;Muito alto
P | Exames complementares | texto_longo""",
        'exame': 'ACV: ictus não palpável, RCR 2T, BNF, sem sopros. Pulsos periféricos palpáveis e simétricos.',
    },
    'Fisioterapia': {
        'nome': 'Fisioterapia - avaliação/evolução',
        'definicao': """S | Dor - EVA (0 a 10) | escala
S | Localização da dor | texto
S | Fatores de piora / melhora | texto
O | Amplitude de movimento (ADM) | texto_longo
O | Força muscular (MRC 0-5) | opcoes | 0;1;2;3;4;5
O | Testes especiais | texto_longo
O | Marcha | opcoes | Normal;Claudicante;Com auxílio;Não deambula
A | Diagnóstico cinético-funcional | texto_longo
P | Condutas realizadas na sessão | texto_longo
P | Orientações domiciliares | texto
P | Evolução em relação à sessão anterior | opcoes | Melhora;Estável;Piora""",
        'exame': '',
        'conduta': 'Cinesioterapia, terapia manual e orientações posturais.',
    },
    'Dermatologia': {
        'nome': 'Dermatologia - consulta',
        'definicao': """S | Tempo de evolução da lesão | texto
S | Prurido | sim_nao
S | Exposição solar / fotoproteção | texto
O | Fototipo (Fitzpatrick) | opcoes | I;II;III;IV;V;VI
O | Tipo de lesão | opcoes | Mácula;Pápula;Placa;Nódulo;Vesícula;Pústula;Úlcera;Outra
O | Localização | texto
O | Tamanho (mm) | numero
O | Dermatoscopia | texto_longo
A | Regra ABCDE alterada | sim_nao
P | Biópsia indicada | sim_nao""",
        'exame': '',
    },
}

# (grupo, nome, unidade, ref_min, ref_max) — valores gerais para adultos; ajuste conforme o laboratório.
EXAMES = [
    ('Glicemia', 'Glicemia de jejum', 'mg/dL', 70, 99),
    ('Glicemia', 'Hemoglobina glicada (HbA1c)', '%', 4.0, 5.6),
    ('Lipidograma', 'Colesterol total', 'mg/dL', None, 190),
    ('Lipidograma', 'HDL', 'mg/dL', 40, None),
    ('Lipidograma', 'LDL', 'mg/dL', None, 130),
    ('Lipidograma', 'Triglicerídeos', 'mg/dL', None, 150),
    ('Função renal', 'Creatinina', 'mg/dL', 0.6, 1.3),
    ('Função renal', 'Ureia', 'mg/dL', 15, 45),
    ('Função renal', 'Ácido úrico', 'mg/dL', 2.5, 7.0),
    ('Função hepática', 'TGO (AST)', 'U/L', None, 40),
    ('Função hepática', 'TGP (ALT)', 'U/L', None, 41),
    ('Tireoide', 'TSH', 'mUI/L', 0.4, 4.5),
    ('Tireoide', 'T4 livre', 'ng/dL', 0.8, 1.8),
    ('Hemograma', 'Hemoglobina', 'g/dL', 12.0, 17.5),
    ('Hemograma', 'Hematócrito', '%', 36, 52),
    ('Hemograma', 'Leucócitos', '/mm³', 4000, 11000),
    ('Hemograma', 'Plaquetas', '/mm³', 150000, 450000),
    ('Eletrólitos', 'Sódio', 'mEq/L', 135, 145),
    ('Eletrólitos', 'Potássio', 'mEq/L', 3.5, 5.0),
    ('Vitaminas e ferro', 'Vitamina D (25-OH)', 'ng/mL', 20, 100),
    ('Vitaminas e ferro', 'Vitamina B12', 'pg/mL', 200, 900),
    ('Vitaminas e ferro', 'Ferritina', 'ng/mL', 15, 300),
    ('Inflamação', 'Proteína C reativa (PCR)', 'mg/L', None, 5),
    ('Outros', 'PSA total', 'ng/mL', None, 4),
]


def criar_modelos_padrao(clinica):
    n = 0
    for esp_nome, m in MODELOS.items():
        esp = Especialidade.objects.filter(clinica=clinica, nome__iexact=esp_nome).first()
        _, criado = ModeloProntuario.objects.get_or_create(
            clinica=clinica, nome=m['nome'],
            defaults={'especialidade': esp, 'definicao': m['definicao'], 'exame_fisico_padrao': m.get('exame', ''),
                      'conduta_padrao': m.get('conduta', '')})
        n += criado
    return n


def criar_exames_padrao(clinica):
    n = 0
    for grupo, nome, un, mn, mx in EXAMES:
        _, criado = ExameLaboratorial.objects.get_or_create(
            clinica=clinica, nome=nome,
            defaults={'grupo': grupo, 'unidade': un, 'ref_min': Decimal(str(mn)) if mn is not None else None,
                      'ref_max': Decimal(str(mx)) if mx is not None else None})
        n += criado
    return n
