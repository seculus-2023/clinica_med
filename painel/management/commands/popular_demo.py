import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from agenda.models import Agendamento, PacoteSessao
from cadastros.models import (Cid, Especialidade, HorarioAtendimento, Medicamento, Medico, Paciente, Procedimento,
                              TipoAtendimento)
from contas.models import Clinica, Vinculo
from contas.services import criar_perfis_padrao, preparar_clinica
from documentos.models import ModeloDocumento
from estoque.models import InsumoAtendimento, MovimentoEstoque, Produto
from financeiro.models import Lancamento
from prontuario.models import Atendimento, HistoricoClinico

Usuario = get_user_model()

NOMES = ['Ana Souza', 'Bruno Lima', 'Carla Mendes', 'Daniel Rocha', 'Eduarda Alves', 'Felipe Costa',
         'Gabriela Nunes', 'Henrique Dias', 'Isabela Martins', 'João Pereira', 'Karina Freitas', 'Lucas Barros',
         'Mariana Teixeira', 'Nicolas Ribeiro', 'Olivia Cardoso', 'Paulo Moreira', 'Renata Gomes', 'Samuel Araujo']
CIDS = [('J06.9', 'Infecção aguda das vias aéreas superiores não especificada'), ('I10', 'Hipertensão essencial'),
        ('E11.9', 'Diabetes mellitus tipo 2 sem complicações'), ('M54.5', 'Dor lombar baixa'),
        ('F41.1', 'Ansiedade generalizada'), ('K29.7', 'Gastrite não especificada'),
        ('M75.1', 'Síndrome do manguito rotador'), ('R51', 'Cefaleia'), ('Z00.0', 'Exame médico geral')]
MODELO_ATESTADO = ('Atesto, para os devidos fins, que o(a) paciente {paciente}, CPF {cpf}, esteve sob meus cuidados '
                   'médicos em {data}, necessitando de afastamento de suas atividades por {dias} dia(s).\nCID: {cid}')
MODELO_DECLARACAO = ('Declaro, para os devidos fins, que {paciente} esteve nesta clínica em {data_atendimento}, '
                     'das {hora_inicio} às {hora_fim}, para atendimento médico.')


class Command(BaseCommand):
    help = 'Cria clínicas, usuários e dados de demonstração.'

    def add_arguments(self, parser):
        parser.add_argument('--senha', default='admin123')

    @transaction.atomic
    def handle(self, *args, **o):
        senha = o['senha']
        random.seed(7)
        admin, criado = Usuario.objects.get_or_create(username='admin', defaults={
            'first_name': 'Administrador', 'is_superuser': True, 'is_staff': True, 'email': 'admin@exemplo.com'})
        if criado:
            admin.set_password(senha)
            admin.save()
        for cod, nome in CIDS:
            Cid.objects.get_or_create(codigo=cod, defaults={'nome': nome, 'categoria': cod[:3]})

        for idx, (nome_c, cidade) in enumerate([('Clínica Vida Plena', 'São Paulo'), ('Centro Médico Bem Estar', 'Campinas')]):
            c, novo = Clinica.objects.get_or_create(nome=nome_c, defaults={
                'cidade': cidade, 'uf': 'SP', 'telefone': '(11) 3000-000%d' % idx, 'whatsapp': '(11) 9900%d-0000' % idx,
                'email': f'contato{idx}@exemplo.com', 'endereco': 'Av. Paulista, %d' % (1000 + idx)})
            if not novo:
                self.stdout.write(f'{nome_c} já existe — pulando.')
                continue
            perfis = criar_perfis_padrao(c)
            Vinculo.objects.get_or_create(usuario=admin, clinica=c, defaults={'perfil': perfis['Administrador']})
            sufixo = '' if idx == 0 else str(idx + 1)

            def usuario(login, nome, perfil):
                u, cr = Usuario.objects.get_or_create(username=login + sufixo, defaults={'first_name': nome})
                if cr:
                    u.set_password(senha)
                    u.save()
                Vinculo.objects.get_or_create(usuario=u, clinica=c, defaults={'perfil': perfis[perfil]})
                return u
            usuario('recepcao', 'Juliana (Recepção)', 'Recepção')
            usuario('financeiro', 'Marcos (Financeiro)', 'Financeiro')
            u_ana = usuario('dra.ana', 'Dra. Ana Paula', 'Médico')
            u_bruno = usuario('dr.bruno', 'Dr. Bruno Reis', 'Médico')

            esp = {n: Especialidade.objects.create(clinica=c, nome=n) for n in
                   ('Clínica geral', 'Cardiologia', 'Fisioterapia', 'Dermatologia')}
            med_ana = Medico.objects.create(clinica=c, nome='Dra. Ana Paula Silva', registro='123456', uf_registro='SP',
                                            usuario=u_ana, cor='#0ea5e9', email='ana@exemplo.com',
                                            acesso_prontuario='completo')
            med_ana.especialidades.add(esp['Clínica geral'], esp['Cardiologia'])
            med_bruno = Medico.objects.create(clinica=c, nome='Dr. Bruno Reis', conselho='CREFITO', registro='98765',
                                              uf_registro='SP', usuario=u_bruno, cor='#8b5cf6',
                                              acesso_prontuario='consulta')
            med_bruno.especialidades.add(esp['Fisioterapia'])
            medicos = [med_ana, med_bruno]
            med_ana.percentual_repasse, med_bruno.percentual_repasse = 60, 50
            med_ana.save(), med_bruno.save()
            c.taxa_credito, c.taxa_debito = Decimal('3.5'), Decimal('1.5')
            c.save()
            for m in medicos:
                for dia in range(0, 5):
                    HorarioAtendimento.objects.create(clinica=c, medico=m, dia_semana=dia, inicio=time(8), fim=time(12))
                    HorarioAtendimento.objects.create(clinica=c, medico=m, dia_semana=dia, inicio=time(14), fim=time(18))
                HorarioAtendimento.objects.create(clinica=c, medico=m, dia_semana=5, inicio=time(8), fim=time(12))

            proc = Procedimento.objects.create(clinica=c, codigo='0301010064', nome='CONSULTA MEDICA EM ATENÇÃO BÁSICA',
                                               origem='sus', complexidade='1', valor_sa=Decimal('10.00'),
                                               competencia='2026/11')
            Procedimento.objects.create(clinica=c, codigo='0302050027', origem='sus', complexidade='2',
                                        nome='ATENDIMENTO FISIOTERAPÊUTICO NAS ALTERAÇÕES MOTORAS',
                                        valor_sa=Decimal('4.67'), competencia='2026/11')
            tipos = [
                TipoAtendimento.objects.create(clinica=c, nome='Consulta clínica', especialidade=esp['Clínica geral'],
                                               duracao_minutos=30, valor=250, valor_convenio=120, procedimento=proc,
                                               retorno_dias=30, agendamento_online=True),
                TipoAtendimento.objects.create(clinica=c, nome='Consulta cardiológica', especialidade=esp['Cardiologia'],
                                               duracao_minutos=40, valor=380, valor_convenio=180),
                TipoAtendimento.objects.create(clinica=c, nome='Sessão de fisioterapia', especialidade=esp['Fisioterapia'],
                                               duracao_minutos=50, valor=150, valor_sessao_pacote=120,
                                               permite_pacote=True, agendamento_online=True),
                TipoAtendimento.objects.create(clinica=c, nome='Retorno', duracao_minutos=20, valor=0),
            ]
            TipoAtendimento.objects.create(clinica=c, nome='Teleconsulta', especialidade=esp['Clínica geral'],
                                           duracao_minutos=30, valor=200, teleconsulta=True, agendamento_online=True)
            for nome, pa, apres, ctrl in [('Dipirona Sódica', 'dipirona monoidratada', '500 MG COM CT BL X 10', False),
                                          ('Amoxicilina', 'amoxicilina tri-hidratada', '500 MG CAP CT X 21', False),
                                          ('Losartana Potássica', 'losartana potássica', '50 MG COM CT X 30', False),
                                          ('Clonazepam', 'clonazepam', '2 MG COM CT X 30', True),
                                          ('Omeprazol', 'omeprazol', '20 MG CAP CT X 28', False)]:
                Medicamento.objects.create(clinica=c, nome=nome, principio_ativo=pa, apresentacao=apres, controlado=ctrl,
                                           tarja='Tarja Preta' if ctrl else 'Tarja Vermelha',
                                           preco_maximo_consumidor=Decimal(random.randint(900, 6000)) / 100,
                                           posologia_padrao='Tomar 1 comprimido de 8/8 horas por 5 dias')
            ModeloDocumento.objects.create(clinica=c, nome='Atestado padrão', tipo='atestado', conteudo=MODELO_ATESTADO)
            ModeloDocumento.objects.create(clinica=c, nome='Declaração de comparecimento', tipo='declaracao',
                                           conteudo=MODELO_DECLARACAO)

            pacientes = []
            for i, n in enumerate(NOMES):
                pacientes.append(Paciente.objects.create(
                    clinica=c, nome=n, cpf=f'{random.randint(100, 999)}.{random.randint(100, 999)}.{random.randint(100, 999)}-{i:02d}',
                    data_nascimento=timezone.localdate() - timedelta(days=random.randint(18 * 365, 80 * 365)),
                    sexo=random.choice('FM'), celular=f'(11) 9{random.randint(1000, 9999)}-{random.randint(1000, 9999)}',
                    email=f'{n.split()[0].lower()}@exemplo.com', convenio=random.choice(['', '', 'Unimed', 'Amil']),
                    origem=random.choice(['indicacao', 'instagram', 'google', 'convenio', 'site']),
                    alergias='Dipirona' if i == 0 else ''))

            hoje = timezone.localdate()
            tz = timezone.get_current_timezone()
            pac = PacoteSessao.objects.create(clinica=c, paciente=pacientes[1], tipo=tipos[2], medico=med_bruno,
                                              quantidade=10, valor_total=1200, data_compra=hoje - timedelta(days=20))
            Lancamento.gerar_parcelas(clinica=c, descricao=f'Pacote 10x Fisioterapia - {pacientes[1]}', total=1200,
                                      parcelas=3, primeiro_vencimento=pac.data_compra, primeira_paga=True, forma='credito',
                                      paciente=pacientes[1], pacote=pac)

            for d in range(-20, 10):
                dia = hoje + timedelta(days=d)
                if dia.weekday() == 6:
                    continue
                for h in random.sample([8, 9, 10, 11, 14, 15, 16, 17], 4):
                    med = random.choice(medicos)
                    tipo = tipos[2] if med is med_bruno else random.choice(tipos[:2])
                    inicio = timezone.make_aware(datetime.combine(dia, time(h, 0)), tz)
                    paciente = random.choice(pacientes)
                    pacote = pac if (med is med_bruno and paciente == pacientes[1] and pac.disponiveis > 0) else None
                    if d < 0:
                        status = random.choices(['concluido', 'faltou', 'cancelado'], [8, 1, 1])[0]
                    elif d == 0:
                        status = random.choice(['confirmado', 'agendado', 'aguardando', 'concluido'])
                    else:
                        status = random.choice(['agendado', 'confirmado'])
                    ag = Agendamento.objects.create(clinica=c, paciente=paciente, medico=med, tipo=tipo, inicio=inicio,
                                                    status=status, pacote=pacote, notificar=d >= 0, criado_por=admin)
                    if status == 'concluido' and not pacote and ag.valor:
                        Lancamento.objects.create(
                            clinica=c, tipo='receita', descricao=f'{tipo} - {paciente}', valor=ag.valor,
                            categoria=Lancamento.categoria_padrao(c, 'receita', 'Atendimentos'), vencimento=dia,
                            status='pago' if random.random() < .85 else 'pendente', paciente=paciente, agendamento=ag,
                            medico=med, forma_pagamento=random.choice(['pix', 'credito', 'debito', 'dinheiro']))
                    if status == 'concluido' and med is med_ana:
                        cid = Cid.objects.order_by('?').first()
                        Atendimento.objects.create(
                            clinica=c, paciente=paciente, medico=med, agendamento=ag, data=inicio,
                            queixa_principal=random.choice(['Dor de cabeça há 3 dias', 'Controle de pressão arterial',
                                                            'Tosse e coriza', 'Check-up anual']),
                            hda='Paciente refere início dos sintomas há alguns dias, sem febre.',
                            pa_sistolica=random.randint(110, 150), pa_diastolica=random.randint(70, 95),
                            fc=random.randint(60, 95), peso=Decimal(random.randint(550, 950)) / 10, altura=170,
                            exame_fisico='BEG, corado, hidratado. ACV: RCR 2T BNF. AR: MV+ sem RA.',
                            cid_principal=cid, hipotese_diagnostica=cid.nome if cid else '',
                            conduta='Orientações gerais. Retorno em 30 dias.', status='finalizado',
                            finalizado_em=inicio + timedelta(minutes=30), criado_por=u_ana)
            HistoricoClinico.objects.create(clinica=c, paciente=pacientes[0], alergias='Dipirona',
                                            doencas_cronicas='Hipertensão arterial', tipo_sanguineo='O+',
                                            medicamentos_uso='Losartana 50mg 1x/dia', tabagismo='nunca')
            for desc, valor, dia in [('Aluguel', 4500, 5), ('Energia elétrica', 620, 10), ('Internet', 199, 15),
                                     ('Material de limpeza', 340, 20)]:
                Lancamento.objects.create(clinica=c, tipo='despesa', descricao=desc, valor=valor,
                                          categoria=Lancamento.categoria_padrao(c, 'despesa', 'Despesas fixas'),
                                          vencimento=hoje.replace(day=dia), fornecedor='Fornecedor',
                                          status='pago' if dia < hoje.day else 'pendente')
            for nome, cat, minimo, qtd in [('Luva de procedimento (cx 100)', 'material', 5, 12),
                                           ('Seringa 5ml', 'material', 50, 30), ('Álcool 70% 1L', 'insumo', 4, 9),
                                           ('Gaze estéril (pct)', 'material', 20, 60)]:
                p = Produto.objects.create(clinica=c, nome=nome, categoria=cat, estoque_minimo=minimo)
                MovimentoEstoque.objects.create(clinica=c, produto=p, tipo='entrada', quantidade=qtd,
                                                custo_unitario=Decimal(random.randint(100, 4000)) / 100,
                                                lote=f'L{random.randint(1000, 9999)}',
                                                validade=hoje + timedelta(days=random.randint(30, 400)))
                if nome.startswith('Gaze'):
                    InsumoAtendimento.objects.create(clinica=c, tipo=tipos[2], produto=p, quantidade=2)
            preparar_clinica(c)
            from prontuario.models import ExameLaboratorial, ResultadoExame
            for nome_ex, valores in (('Glicemia de jejum', (94, 103, 112)), ('LDL', (168, 145, 128)),
                                     ('Hemoglobina glicada (HbA1c)', (5.5, 5.9, 6.2)), ('Creatinina', (0.9, 1.0, 1.0))):
                ex = ExameLaboratorial.objects.get(clinica=c, nome=nome_ex)
                for i, v in enumerate(valores):
                    ResultadoExame.objects.create(clinica=c, paciente=pacientes[0], exame=ex, valor=Decimal(str(v)),
                                                  data=hoje - timedelta(days=180 - 90 * i))
            self.stdout.write(self.style.SUCCESS(f'{nome_c} criada.'))
        self.stdout.write(self.style.SUCCESS(
            f'Pronto! Logins (senha "{senha}"): admin, recepcao, financeiro, dra.ana (prontuário completo), '
            f'dr.bruno (prontuário somente consulta).'))
