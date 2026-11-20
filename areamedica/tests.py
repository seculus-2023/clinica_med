from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento
from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.models import Clinica, Perfil, Usuario, Vinculo


class AreaMedicaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clinica = Clinica.objects.create(nome='Clínica Teste')
        cls.perfil_med = Perfil.objects.create(clinica=cls.clinica, nome='Médico',
                                               permissoes={'agenda': 'ver'})
        cls.perfil_rec = Perfil.objects.create(clinica=cls.clinica, nome='Recepção',
                                               permissoes={'agenda': 'editar'})
        cls.perfil_fin = Perfil.objects.create(clinica=cls.clinica, nome='Financeiro',
                                               permissoes={'financeiro': 'editar'})

        cls.u_med = Usuario.objects.create_user('dra', password='senha123')
        cls.u_rec = Usuario.objects.create_user('recep', password='senha123')
        cls.u_fin = Usuario.objects.create_user('fin', password='senha123')
        Vinculo.objects.create(usuario=cls.u_med, clinica=cls.clinica, perfil=cls.perfil_med)
        Vinculo.objects.create(usuario=cls.u_rec, clinica=cls.clinica, perfil=cls.perfil_rec)
        Vinculo.objects.create(usuario=cls.u_fin, clinica=cls.clinica, perfil=cls.perfil_fin)

        cls.medico = Medico.objects.create(clinica=cls.clinica, nome='Dra. Ana', usuario=cls.u_med,
                                           acesso_prontuario='nenhum')
        cls.outro = Medico.objects.create(clinica=cls.clinica, nome='Dr. Bruno')
        cls.tipo = TipoAtendimento.objects.create(clinica=cls.clinica, nome='Consulta', duracao_minutos=30)
        cls.paciente = Paciente.objects.create(clinica=cls.clinica, nome='Carlos Souza', alergias='Dipirona')

    def setUp(self):
        agora = timezone.localtime()
        base = agora.replace(hour=12, minute=0, second=0, microsecond=0)
        self.ag = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=self.medico,
                                             tipo=self.tipo, inicio=base, notificar=False)
        self.ag_outro = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=self.outro,
                                                   tipo=self.tipo, inicio=base + timedelta(hours=1),
                                                   notificar=False)

    def entrar(self, usuario):
        self.client.force_login(usuario)
        s = self.client.session
        s['clinica_id'] = self.clinica.pk
        s.save()

    # ---- acesso ----
    def test_anonimo_vai_para_login(self):
        r = self.client.get(reverse('areamedica:agenda'))
        self.assertRedirects(r, f"{reverse('areamedica:entrar')}?next=/medico/", fetch_redirect_response=False)

    def test_pagina_de_login_abre(self):
        r = self.client.get(reverse('areamedica:entrar'))
        self.assertContains(r, 'Minha agenda')

    def test_login_redireciona_para_agenda(self):
        r = self.client.post(reverse('areamedica:entrar'), {'username': 'dra', 'password': 'senha123'})
        self.assertRedirects(r, reverse('areamedica:agenda'), fetch_redirect_response=False)

    def test_login_ignora_next_fora_da_area(self):
        r = self.client.post(reverse('areamedica:entrar'),
                             {'username': 'dra', 'password': 'senha123', 'next': 'https://malicioso.com/medico/'})
        self.assertRedirects(r, reverse('areamedica:agenda'), fetch_redirect_response=False)

    def test_clinica_unica_escolhida_automaticamente(self):
        self.client.force_login(self.u_med)
        r = self.client.get(reverse('areamedica:agenda'))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(self.client.session['clinica_id'], self.clinica.pk)

    def test_manifest(self):
        r = self.client.get(reverse('areamedica:manifest'))
        self.assertEqual(r['Content-Type'], 'application/manifest+json')
        self.assertEqual(r.json()['scope'], '/medico/')

    # ---- agenda ----
    def test_medico_ve_somente_os_proprios_pacientes(self):
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:agenda'))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['agendamentos'], [self.ag])
        self.assertTrue(r.context['proprio'])
        self.assertContains(r, 'Carlos Souza')
        self.assertContains(r, 'Alergia')

    def test_cancelado_fica_oculto(self):
        self.ag.status = 'cancelado'
        self.ag.save()
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:agenda'))
        self.assertEqual(r.context['agendamentos'], [])
        r = self.client.get(reverse('areamedica:agenda') + '?cancelados=1')
        self.assertEqual(r.context['agendamentos'], [self.ag])

    def test_lista_parcial(self):
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:agenda') + '?parcial=1')
        self.assertTemplateUsed(r, 'areamedica/_lista.html')
        self.assertTemplateNotUsed(r, 'areamedica/agenda.html')

    def test_recepcao_escolhe_o_medico(self):
        self.entrar(self.u_rec)
        r = self.client.get(reverse('areamedica:agenda') + f'?medico={self.outro.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.context['proprio'])
        self.assertEqual(r.context['agendamentos'], [self.ag_outro])

    def test_usuario_sem_agenda_e_sem_medico_e_bloqueado(self):
        self.entrar(self.u_fin)
        r = self.client.get(reverse('areamedica:agenda'))
        self.assertEqual(r.status_code, 403)
        self.assertTemplateUsed(r, 'areamedica/sem_vinculo.html')

    # ---- paciente ----
    def test_ficha_do_paciente(self):
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:paciente', args=[self.ag.pk]))
        self.assertContains(r, 'Carlos Souza')
        self.assertContains(r, 'Dipirona')

    def test_medico_nao_abre_atendimento_de_outro(self):
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:paciente', args=[self.ag_outro.pk]))
        self.assertEqual(r.status_code, 404)

    # ---- status ----
    def test_marcar_chegada_e_concluir(self):
        self.entrar(self.u_med)
        url = reverse('areamedica:status', args=[self.ag.pk])
        r = self.client.post(url, {'status': 'aguardando', 'next': '/medico/?data=2026-01-01'})
        self.assertRedirects(r, '/medico/?data=2026-01-01', fetch_redirect_response=False)
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, 'aguardando')
        self.assertIsNotNone(self.ag.chegada_em)

        self.client.post(url, {'status': 'em_atendimento'})
        self.client.post(url, {'status': 'concluido'})
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, 'concluido')
        self.assertIsNotNone(self.ag.atendimento_fim)

    def test_status_nao_permitido(self):
        self.entrar(self.u_med)
        r = self.client.post(reverse('areamedica:status', args=[self.ag.pk]), {'status': 'cancelado'})
        self.assertEqual(r.status_code, 403)
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, 'agendado')

    def test_next_externo_e_ignorado(self):
        self.entrar(self.u_med)
        r = self.client.post(reverse('areamedica:status', args=[self.ag.pk]),
                             {'status': 'aguardando', 'next': 'https://malicioso.com/'})
        self.assertTrue(r['Location'].startswith('/medico/?data='))

    def test_status_exige_post(self):
        self.entrar(self.u_med)
        r = self.client.get(reverse('areamedica:status', args=[self.ag.pk]))
        self.assertEqual(r.status_code, 405)

    def test_agendamento_cancelado_nao_muda(self):
        self.ag.status = 'cancelado'
        self.ag.save()
        self.entrar(self.u_med)
        self.client.post(reverse('areamedica:status', args=[self.ag.pk]), {'status': 'aguardando'})
        self.ag.refresh_from_db()
        self.assertEqual(self.ag.status, 'cancelado')

    def test_sair(self):
        self.entrar(self.u_med)
        r = self.client.post(reverse('areamedica:sair'))
        self.assertRedirects(r, reverse('areamedica:entrar'), fetch_redirect_response=False)
        self.assertNotIn('_auth_user_id', self.client.session)
