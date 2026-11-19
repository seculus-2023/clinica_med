"""Base inicial de interações medicamentosas clinicamente relevantes e bem estabelecidas.

ATENÇÃO: base de apoio à decisão, NÃO substitui bulas, compêndios oficiais nem a avaliação do prescritor/farmacêutico.
A clínica pode editar, desativar e importar novas interações (CSV) em Cadastros > Interações medicamentosas.
"""
AINES = ('ibuprofeno, naproxeno, diclofenaco, cetoprofeno, nimesulida, meloxicam, piroxicam, cetorolaco, '
         'indometacina, celecoxibe, etoricoxibe')
ISRS = 'fluoxetina, sertralina, paroxetina, citalopram, escitalopram, fluvoxamina'
IECA = 'enalapril, captopril, lisinopril, ramipril, perindopril'
BRA = 'losartana, valsartana, candesartana, olmesartana, irbesartana, telmisartana'
OPIOIDES = 'morfina, codeina, tramadol, oxicodona, fentanil, metadona, tapentadol'
BENZO = 'diazepam, clonazepam, alprazolam, lorazepam, bromazepam, midazolam, cloxazolam'
FONTE = 'Referência clínica geral (bulas e literatura). Confirme em fonte oficial.'

INTERACOES = [
    ('varfarina', 'acido acetilsalicilico, aas', 'grave', 'Aumento importante do risco de sangramento.',
     'Evitar a associação ou monitorar INR e sinais de sangramento.'),
    ('varfarina', AINES, 'grave', 'Aumento do risco de sangramento gastrointestinal e de outros sítios.',
     'Preferir paracetamol; se necessário, monitorar INR e usar gastroproteção.'),
    ('varfarina', 'fluconazol, metronidazol, amiodarona, sulfametoxazol', 'grave',
     'Inibição do metabolismo da varfarina com aumento do INR e risco de sangramento.',
     'Reduzir dose da varfarina e monitorar INR de perto.'),
    ('varfarina', 'paracetamol', 'moderada', 'Uso regular de doses altas pode elevar o INR.',
     'Monitorar INR se uso contínuo.'),
    ('sildenafila, tadalafila, vardenafila', 'nitroglicerina, isossorbida, mononitrato, dinitrato, nitroprussiato',
     'contraindicada', 'Hipotensão grave e potencialmente fatal.', 'Associação contraindicada.'),
    (ISRS, 'selegilina, tranilcipromina, moclobemida, linezolida', 'contraindicada',
     'Risco de síndrome serotoninérgica.', 'Não associar; respeitar intervalo de washout.'),
    ('tramadol', ISRS + ', venlafaxina, duloxetina', 'grave',
     'Risco de síndrome serotoninérgica e redução do limiar convulsivo.', 'Evitar ou monitorar sinais clínicos.'),
    (ISRS, 'acido acetilsalicilico, aas, ' + AINES, 'moderada', 'Aumento do risco de sangramento gastrointestinal.',
     'Considerar gastroproteção e monitorar.'),
    ('clopidogrel', 'omeprazol, esomeprazol', 'moderada',
     'Redução da ativação do clopidogrel (CYP2C19) e do efeito antiplaquetário.', 'Preferir pantoprazol.'),
    ('sinvastatina, lovastatina', 'claritromicina, eritromicina, itraconazol, cetoconazol, posaconazol',
     'contraindicada', 'Aumento dos níveis da estatina com risco de miopatia/rabdomiólise.',
     'Suspender a estatina durante o tratamento ou usar alternativa.'),
    ('sinvastatina', 'amiodarona, verapamil, diltiazem', 'grave', 'Risco aumentado de miopatia.',
     'Limitar a dose da sinvastatina conforme bula.'),
    ('espironolactona, amilorida, eplerenona, cloreto de potassio', IECA + ', ' + BRA, 'grave',
     'Risco de hipercalemia.', 'Monitorar potássio e função renal.'),
    (IECA, BRA, 'grave', 'Duplo bloqueio do sistema renina-angiotensina: hipercalemia, hipotensão e lesão renal.',
     'Evitar a associação.'),
    ('litio, carbonato de litio', AINES + ', hidroclorotiazida, clortalidona, ' + IECA + ', ' + BRA, 'grave',
     'Aumento dos níveis séricos de lítio com risco de toxicidade.', 'Evitar ou monitorar litemia.'),
    ('digoxina', 'amiodarona, claritromicina, verapamil, propafenona', 'grave',
     'Aumento dos níveis de digoxina (toxicidade digitálica).', 'Reduzir dose e monitorar nível sérico.'),
    ('metotrexato', 'sulfametoxazol, trimetoprima', 'grave', 'Toxicidade medular grave (pancitopenia).',
     'Evitar a associação.'),
    (OPIOIDES, BENZO + ', zolpidem', 'grave', 'Depressão respiratória e sedação profunda, risco de óbito.',
     'Evitar; se necessário, menores doses e monitorização.'),
    ('ciprofloxacino', 'teofilina, aminofilina', 'grave', 'Aumento dos níveis de teofilina (convulsões, arritmias).',
     'Evitar ou monitorar níveis.'),
    ('tizanidina', 'ciprofloxacino, fluvoxamina', 'contraindicada', 'Hipotensão e sedação acentuadas.',
     'Associação contraindicada.'),
    ('rifampicina, carbamazepina, fenitoina, fenobarbital, topiramato',
     'etinilestradiol, levonorgestrel, desogestrel, gestodeno, drospirenona', 'grave',
     'Indução enzimática com redução da eficácia contraceptiva.', 'Orientar método contraceptivo adicional.'),
    ('alopurinol', 'azatioprina, mercaptopurina', 'grave', 'Toxicidade medular por inibição da xantina oxidase.',
     'Reduzir a dose do imunossupressor ou evitar.'),
    (AINES, IECA + ', ' + BRA + ', hidroclorotiazida, furosemida', 'moderada',
     'Redução do efeito anti-hipertensivo e risco de lesão renal.', 'Monitorar pressão e função renal.'),
    (AINES, 'acido acetilsalicilico, aas', 'moderada',
     'Maior risco de sangramento gastrointestinal; ibuprofeno pode reduzir o efeito cardioprotetor do AAS.',
     'Evitar uso concomitante regular.'),
    ('claritromicina, eritromicina', 'colchicina', 'grave', 'Toxicidade da colchicina.', 'Evitar ou reduzir dose.'),
    ('claritromicina, eritromicina', 'carbamazepina', 'grave', 'Aumento dos níveis de carbamazepina.',
     'Monitorar ou usar alternativa.'),
    ('fluconazol', 'fenitoina', 'moderada', 'Aumento dos níveis de fenitoína.', 'Monitorar nível sérico.'),
    ('propranolol, atenolol, metoprolol, carvedilol, bisoprolol', 'verapamil, diltiazem', 'grave',
     'Bradicardia, bloqueio AV e hipotensão.', 'Evitar ou monitorar ECG.'),
    ('propranolol', 'insulina, glibenclamida, gliclazida, glimepirida', 'moderada',
     'Mascaramento dos sintomas de hipoglicemia.', 'Orientar o paciente e monitorar glicemia.'),
    ('levotiroxina', 'carbonato de calcio, sulfato ferroso, hidroxido de aluminio, sevelamer', 'leve',
     'Redução da absorção da levotiroxina.', 'Separar as tomadas em pelo menos 4 horas.'),
    ('ciprofloxacino, levofloxacino, tetraciclina, doxiciclina',
     'carbonato de calcio, sulfato ferroso, hidroxido de aluminio, hidroxido de magnesio, zinco', 'moderada',
     'Redução da absorção do antibiótico.', 'Separar as tomadas (2h antes ou 6h depois).'),
    ('metformina', 'contraste iodado', 'moderada', 'Risco de acidose lática em caso de lesão renal.',
     'Suspender conforme protocolo de contraste.'),
]


def carregar(apagar_antigas=False):
    from .models import InteracaoMedicamentosa
    if apagar_antigas:
        InteracaoMedicamentosa.objects.filter(fonte=FONTE).delete()
    n = 0
    for a, b, grav, efeito, conduta in INTERACOES:
        _, criado = InteracaoMedicamentosa.objects.get_or_create(
            substancia_a=a, substancia_b=b,
            defaults={'gravidade': grav, 'efeito': efeito, 'conduta': conduta, 'fonte': FONTE})
        n += criado
    return n
