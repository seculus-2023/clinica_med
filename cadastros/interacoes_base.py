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
    return n + carregar_extra()

QT_A = 'amiodarona, sotalol, haloperidol'
QT_B = 'azitromicina, claritromicina, eritromicina, levofloxacino, moxifloxacino, ondansetrona, domperidona'
TRIPTANOS = 'sumatriptana, rizatriptana, naratriptana, zolmitriptana'
CORTIC = 'prednisona, prednisolona, dexametasona, betametasona, metilprednisolona, hidrocortisona'
AZOIS_FORTES = 'cetoconazol, itraconazol, claritromicina, ritonavir'
IMUNO = 'ciclosporina, tacrolimo'

INTERACOES_EXTRA = [
    (QT_A, QT_B, 'grave', 'Prolongamento do intervalo QT com risco de arritmia (torsades de pointes).',
     'Evitar a associação; se inevitável, ECG e controle de potássio/magnésio.'),
    ('metoclopramida', 'haloperidol, risperidona, olanzapina', 'moderada', 'Aumento de efeitos extrapiramidais.',
     'Evitar uso conjunto prolongado.'),
    ('sildenafila, tadalafila, vardenafila', 'doxazosina, terazosina, prazosina', 'moderada',
     'Hipotensão sintomática.', 'Iniciar com doses baixas e espaçar as tomadas.'),
    ('tamoxifeno', 'fluoxetina, paroxetina, bupropiona', 'grave',
     'Redução da conversão do tamoxifeno em metabólito ativo (CYP2D6), com perda de eficácia.',
     'Preferir antidepressivo sem inibição forte do CYP2D6.'),
    ('codeina', 'fluoxetina, paroxetina, bupropiona', 'moderada', 'Redução do efeito analgésico da codeína (CYP2D6).',
     'Considerar outro analgésico.'),
    ('varfarina', 'carbamazepina, rifampicina, fenitoina, fenobarbital', 'grave',
     'Redução do efeito anticoagulante (indução enzimática).', 'Monitorar INR e ajustar dose.'),
    ('acido valproico, valproato, divalproato', 'meropenem, imipenem, ertapenem', 'grave',
     'Queda acentuada dos níveis de valproato com risco de convulsões.', 'Evitar; usar outro antibiótico.'),
    ('acido valproico, valproato, divalproato', 'lamotrigina', 'grave',
     'Aumento dos níveis de lamotrigina, com risco de reações cutâneas graves.', 'Ajustar a dose da lamotrigina.'),
    ('teofilina, aminofilina', 'eritromicina, claritromicina', 'moderada', 'Aumento dos níveis de teofilina.',
     'Monitorar níveis e sintomas de toxicidade.'),
    ('colchicina', 'ciclosporina, cetoconazol, itraconazol, ritonavir', 'grave', 'Toxicidade da colchicina.',
     'Evitar ou reduzir dose.'),
    (IMUNO, 'cetoconazol, itraconazol, fluconazol, voriconazol, claritromicina, eritromicina, diltiazem, verapamil',
     'grave', 'Aumento dos níveis do imunossupressor (nefrotoxicidade).', 'Monitorar nível sérico e função renal.'),
    (IMUNO, 'rifampicina, carbamazepina, fenitoina, fenobarbital', 'grave',
     'Redução dos níveis do imunossupressor com risco de rejeição.', 'Monitorar nível sérico.'),
    ('espironolactona, amilorida', 'sulfametoxazol, trimetoprima', 'grave', 'Risco de hipercalemia grave.',
     'Evitar ou monitorar potássio.'),
    ('enalapril, captopril, lisinopril, ramipril, losartana, valsartana, candesartana', 'sulfametoxazol, trimetoprima',
     'moderada', 'Risco de hipercalemia.', 'Monitorar potássio, especialmente em idosos e renais.'),
    ('insulina, glibenclamida, gliclazida, glimepirida', 'levofloxacino, ciprofloxacino, moxifloxacino', 'moderada',
     'Hipo ou hiperglicemia.', 'Monitorar glicemia.'),
    ('glibenclamida, glimepirida, gliclazida', 'fluconazol', 'moderada', 'Aumento do risco de hipoglicemia.',
     'Monitorar glicemia.'),
    ('linezolida', 'venlafaxina, duloxetina, tramadol, bupropiona', 'grave', 'Risco de síndrome serotoninérgica.',
     'Evitar a associação.'),
    (TRIPTANOS, 'fluoxetina, sertralina, paroxetina, citalopram, escitalopram, venlafaxina, duloxetina', 'moderada',
     'Risco de síndrome serotoninérgica.', 'Orientar sinais de alerta.'),
    (TRIPTANOS, 'ergotamina, di-hidroergotamina', 'contraindicada', 'Vasoconstrição prolongada.',
     'Intervalo mínimo de 24 horas entre os medicamentos.'),
    ('ergotamina, di-hidroergotamina', AZOIS_FORTES + ', eritromicina', 'contraindicada',
     'Ergotismo (isquemia grave de extremidades).', 'Associação contraindicada.'),
    ('ciprofloxacino, levofloxacino, moxifloxacino, norfloxacino', CORTIC, 'moderada',
     'Aumento do risco de tendinite e ruptura de tendão.', 'Orientar o paciente; cautela em idosos.'),
    (AINES, CORTIC, 'moderada', 'Aumento do risco de úlcera e sangramento gastrointestinal.',
     'Considerar gastroproteção.'),
    (AINES, 'metotrexato', 'grave', 'Redução da eliminação do metotrexato com toxicidade.',
     'Evitar com doses altas de metotrexato; monitorar.'),
    ('digoxina', 'furosemida, hidroclorotiazida, clortalidona, indapamida', 'moderada',
     'Hipocalemia pelo diurético aumenta o risco de toxicidade digitálica.', 'Monitorar potássio.'),
    ('propranolol, atenolol, metoprolol, carvedilol, bisoprolol', 'clonidina', 'moderada',
     'Hipertensão de rebote na suspensão da clonidina.', 'Retirar o beta-bloqueador antes da clonidina.'),
    ('alopurinol', 'amoxicilina, ampicilina', 'leve', 'Maior incidência de exantema (rash).', 'Observar.'),
    ('lamotrigina', 'etinilestradiol, levonorgestrel, desogestrel, gestodeno', 'moderada',
     'Redução dos níveis de lamotrigina.', 'Ajustar dose e monitorar resposta.'),
    ('sinvastatina, lovastatina', 'fluconazol, diltiazem, verapamil, anlodipino', 'moderada',
     'Aumento dos níveis da estatina (miopatia).', 'Limitar dose conforme bula.'),
    ('metotrexato', 'omeprazol, esomeprazol, pantoprazol', 'moderada',
     'Aumento dos níveis de metotrexato em doses altas.', 'Considerar suspender o IBP.'),
    ('clozapina', 'carbamazepina', 'grave', 'Aumento do risco de agranulocitose.', 'Evitar a associação.'),
]


def carregar_extra():
    from .models import InteracaoMedicamentosa
    n = 0
    for a, b, grav, efeito, conduta in INTERACOES_EXTRA:
        n += InteracaoMedicamentosa.objects.get_or_create(
            substancia_a=a, substancia_b=b,
            defaults={'gravidade': grav, 'efeito': efeito, 'conduta': conduta, 'fonte': FONTE})[1]
    return n
