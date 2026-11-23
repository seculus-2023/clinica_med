from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.models import Clinica, Perfil, Usuario, Vinculo
from convenios.models import Operadora, Plano, PrecoConvenio

from .models import Agendamento, PacoteSessao


class PrecoTabelaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clinica = Clinica.objects.create(nome='Clínica Teste')
        cls.outra = Clinica.objects.create(nome='Outra')
        perfil = Perfil.objects.create(clinica=cls.clinica, nome='Recepção', permissoes={'agenda': 'editar'})
        cls.user = Usuario.objects.create_user('recep', password='senha123')
        Vinculo.objects.create(usuario=cls.user, clinica=cls.clinica, perfil=perfil)
        cls.medico = Medico.objects.create(clinica=cls.clinica, nome='Dra. Ana')
        cls.paciente = Paciente.objects.create(clinica=cls.clinica, nome='Carlos')
        cls.tipo = TipoAtendimento.objects.create(clinica=cls.clinica, nome='Consulta', valor=Decimal('200.00'),
                                                  valor_convenio=Decimal('120.00'))
        cls.tipo2 = TipoAtendimento.objects.create(clinica=cls.clinica, nome='Retorno', valor=Decimal('90.00'))
        cls.tipo_outra = TipoAtendimento.objects.create(clinica=cls.outra, nome='Alheio', valor=Decimal('999.00'))
        cls.op = Operadora.objects.create(clinica=cls.clinica, nome='Saúde X')
        cls.plano = Plano.objects.create(clinica=cls.clinica, operadora=cls.op, nome='Ouro')
        PrecoConvenio.objects.create(clinica=cls.clinica, operadora=cls.op, tipo=cls.tipo, valor=Decimal('150.00'))
        PrecoConvenio.objects.create(clinica=cls.clinica, operadora=cls.op, plano=cls.plano, tipo=cls.tipo,
                                     valor=Decimal('175.00'))
        cls.pacote = PacoteSessao.objects.create(clinica=cls.clinica, paciente=cls.paciente, tipo=cls.tipo,
                                                 quantidade=5, valor_total=Decimal('500.00'))

    def setUp(self):
        self.client.force_login(self.user)
        s = self.client.session
        s['clinica_id'] = self.clinica.pk
        s.save()
        self.url = reverse('agenda:api_preco')

    def preco(self, **params):
        return self.client.get(self.url, params).json()['valor']

    def test_ordem_de_precos(self):
        self.assertEqual(self.preco(tipo=self.tipo.pk), '200.00')
        self.assertEqual(self.preco(tipo=self.tipo.pk, convenio=1), '120.00')
        self.assertEqual(self.preco(tipo=self.tipo.pk, operadora=self.op.pk), '150.00')
        self.assertEqual(self.preco(tipo=self.tipo.pk, operadora=self.op.pk, plano=self.plano.pk), '175.00')
        self.assertEqual(self.preco(tipo=self.tipo.pk, pacote=self.pacote.pk), '0.00')

    def test_nao_expoe_outra_clinica_e_ignora_id_invalido(self):
        self.assertIsNone(self.preco(tipo=self.tipo_outra.pk))
        self.assertIsNone(self.preco(tipo='abc'))

    def dados(self, **kw):
        inicio = timezone.localtime() + timedelta(days=2)
        return {'paciente': self.paciente.pk, 'medico': self.medico.pk, 'tipo': self.tipo.pk,
                'inicio': inicio.strftime('%Y-%m-%dT%H:%M'), 'status': 'agendado', 'autorizacao_status': 'nao_requer',
                **kw}

    def test_valor_diferente_digitado_e_mantido(self):
        self.client.post(reverse('agenda:novo'), self.dados(valor='180,00', valor_digitado='1'))
        self.assertEqual(Agendamento.objects.get().valor, Decimal('180.00'))

    def test_edicao_mantem_valor_redigitado_ao_trocar_tipo(self):
        ag = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=self.medico,
                                        tipo=self.tipo, inicio=timezone.now() + timedelta(days=2),
                                        valor=Decimal('200.00'), notificar=False)
        dados = self.dados(tipo=self.tipo2.pk, valor='200,00', valor_digitado='1',
                           inicio=timezone.localtime(ag.inicio).strftime('%Y-%m-%dT%H:%M'))
        self.client.post(reverse('agenda:editar', args=[ag.pk]), dados)
        ag.refresh_from_db()
        self.assertEqual((ag.tipo_id, ag.valor), (self.tipo2.pk, Decimal('200.00')))

    def test_edicao_sem_digitar_recalcula_ao_trocar_tipo(self):
        ag = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=self.medico,
                                        tipo=self.tipo, inicio=timezone.now() + timedelta(days=2),
                                        valor=Decimal('200.00'), notificar=False)
        dados = self.dados(tipo=self.tipo2.pk, valor='200,00',
                           inicio=timezone.localtime(ag.inicio).strftime('%Y-%m-%dT%H:%M'))
        self.client.post(reverse('agenda:editar', args=[ag.pk]), dados)
        ag.refresh_from_db()
        self.assertEqual(ag.valor, Decimal('90.00'))

    def test_formulario_traz_alerta(self):
        r = self.client.get(reverse('agenda:novo'))
        self.assertContains(r, 'id="alertaValor"')
        self.assertContains(r, self.url)
