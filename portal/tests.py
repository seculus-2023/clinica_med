import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento
from cadastros.models import HorarioAtendimento, Medico, Paciente, TipoAtendimento
from cadastros.views import PacienteForm
from contas.models import Clinica, Lembrete
from documentos.models import Documento, ItemPrescricao
from notificacoes.models import Notificacao
from prontuario.models import Atendimento

from .models import AvisoPaciente

CPF = '123.456.789-09'
NASC = date(1980, 5, 10)


class AppPacienteTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.c = Clinica.objects.create(nome='Clínica Teste', agendamento_online=True, online_antecedencia_horas=0,
                                       online_dias=30, notificar_email=True, notificar_whatsapp=False)
        cls.outra = Clinica.objects.create(nome='Outra')
        cls.p = Paciente.objects.create(clinica=cls.c, nome='Maria', cpf=CPF, data_nascimento=NASC,
                                        email='maria@example.com', acesso_app=True,
                                        consentimento_lgpd_em=timezone.now())
        cls.sem_app = Paciente.objects.create(clinica=cls.c, nome='João', cpf='98765432100', data_nascimento=NASC,
                                              email='joao@example.com')
        cls.medico = Medico.objects.create(clinica=cls.c, nome='Dra. Ana', agenda_online=True)
        cls.tipo = TipoAtendimento.objects.create(clinica=cls.c, nome='Consulta', valor=Decimal('100'),
                                                  agendamento_online=True, duracao_minutos=30)
        for dia in range(7):
            HorarioAtendimento.objects.create(clinica=cls.c, medico=cls.medico, dia_semana=dia, inicio=time(8),
                                              fim=time(18))

    def url(self, nome, *a):
        return reverse(f'portal:{nome}', args=[self.c.codigo_publico, *a])

    def logar(self, paciente=None):
        s = self.client.session
        s['portal'] = {'clinica': self.c.pk, 'paciente': (paciente or self.p).pk,
                       'expira': (timezone.now() + timedelta(hours=1)).timestamp()}
        s.save()

    def consulta(self, paciente=None, dias=3, **kw):
        ini = timezone.localtime() + timedelta(days=dias)
        return Agendamento.objects.create(clinica=self.c, paciente=paciente or self.p, medico=self.medico,
                                          tipo=self.tipo, inicio=ini.replace(hour=9, minute=0, second=0, microsecond=0),
                                          notificar=False, **kw)

    def pedir_codigo(self, cpf=CPF):
        return self.client.post(self.url('entrar'), {'etapa': 'dados', 'cpf': cpf, 'nascimento': '1980-05-10'})

    def test_login_com_cpf_e_codigo(self):
        self.pedir_codigo()
        msg = Notificacao.objects.get(evento='portal_codigo').mensagem
        codigo = re.search(r'\b(\d{6})\b', msg).group(1)
        r = self.client.post(self.url('entrar'), {'etapa': 'codigo', 'codigo': codigo})
        self.assertRedirects(r, self.url('inicio'), fetch_redirect_response=False)
        r = self.client.get(self.url('inicio'))
        self.assertContains(r, 'Olá, Maria')
        self.assertEqual(r['Cache-Control'], 'private, no-store')

    def test_sem_liberacao_nao_recebe_codigo(self):
        r = self.pedir_codigo('987.654.321-00')
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Notificacao.objects.filter(evento='portal_codigo').exists())
        self.assertContains(self.client.get(self.url('entrar')), 'código de 6 dígitos')

    def test_limite_de_codigos_vale_entre_sessoes(self):
        for _ in range(5):
            self.client.cookies.clear()
            self.pedir_codigo()
        self.assertEqual(Notificacao.objects.filter(evento='portal_codigo').count(), 3)

    def test_revogar_acesso_derruba_sessao(self):
        self.logar()
        self.assertEqual(self.client.get(self.url('inicio')).status_code, 200)
        Paciente.objects.filter(pk=self.p.pk).update(acesso_app=False)
        self.assertRedirects(self.client.get(self.url('inicio')), self.url('entrar'), fetch_redirect_response=False)
        self.assertEqual(self.client.get(self.url('entrar')).status_code, 200)

    def test_exige_termo_lgpd(self):
        Paciente.objects.filter(pk=self.p.pk).update(consentimento_lgpd_em=None)
        self.logar()
        self.assertRedirects(self.client.get(self.url('medicoes')), self.url('termo'), fetch_redirect_response=False)
        self.client.post(self.url('termo'), {'aceito': 'on'})
        self.assertEqual(self.client.get(self.url('medicoes')).status_code, 200)

    def test_confirmar_e_cancelar(self):
        self.logar()
        ag = self.consulta()
        self.client.post(self.url('confirmar', ag.pk))
        ag.refresh_from_db()
        self.assertEqual((ag.status, ag.confirmado_por), ('confirmado', 'paciente'))
        self.client.post(self.url('cancelar', ag.pk))
        ag.refresh_from_db()
        self.assertEqual(ag.status, 'cancelado')
        self.assertTrue(Lembrete.objects.filter(clinica=self.c, titulo__startswith='Paciente cancelou').exists())

    def test_nao_altera_consulta_de_outro_paciente(self):
        self.logar()
        ag = self.consulta(self.sem_app)
        self.assertEqual(self.client.post(self.url('confirmar', ag.pk)).status_code, 404)
        self.assertEqual(self.client.post(self.url('cancelar', ag.pk)).status_code, 404)
        self.assertEqual(self.client.get(self.url('confirmar', ag.pk)).status_code, 405)

    def _slot(self, dias=3, hora=10):
        d = timezone.localdate() + timedelta(days=dias)
        return timezone.make_aware(datetime.combine(d, time(hora)))

    def test_agendar_horario_livre_e_recusar_ocupado(self):
        from cadastros.models import Especialidade
        esp = Especialidade.objects.create(clinica=self.c, nome='Clínica geral')
        self.medico.especialidades.add(esp)
        self.logar()
        slot = self._slot()
        url = self.url('agendar') + f'?esp={esp.pk}&medico={self.medico.pk}&tipo={self.tipo.pk}'
        r = self.client.post(url, {'slot': slot.isoformat()})
        self.assertRedirects(r, self.url('inicio'), fetch_redirect_response=False)
        self.assertEqual(Agendamento.objects.get(paciente=self.p).inicio, slot)
        r = self.client.post(url, {'slot': slot.isoformat()})
        self.assertContains(r, 'não está mais disponível')
        r = self.client.post(url, {'slot': self._slot(dias=60).isoformat()})
        self.assertContains(r, 'não está mais disponível')
        self.assertEqual(Agendamento.objects.filter(paciente=self.p).count(), 1)
        self.assertEqual(self.client.post(url, {'slot': '2026-13-45T10:00:00'}).status_code, 200)

    def test_medicacoes_e_medicoes_sem_dados_clinicos_privados(self):
        self.logar()
        doc = Documento.objects.create(clinica=self.c, paciente=self.p, medico=self.medico, tipo='receita')
        ItemPrescricao.objects.create(documento=doc, descricao='Losartana 50mg', posologia='1 comprimido ao dia')
        oculta = Documento.objects.create(clinica=self.c, paciente=self.p, medico=self.medico, tipo='receita',
                                          visivel_paciente=False)
        ItemPrescricao.objects.create(documento=oculta, descricao='Remedio oculto')
        r = self.client.get(self.url('medicacoes'))
        self.assertContains(r, 'Losartana 50mg')
        self.assertNotContains(r, 'Remedio oculto')
        Atendimento.objects.create(clinica=self.c, paciente=self.p, medico=self.medico, status='finalizado',
                                   pa_sistolica=120, pa_diastolica=80, anotacoes_privadas='SEGREDO-CLINICO',
                                   hipotese_diagnostica='HIPOTESE-X')
        Atendimento.objects.create(clinica=self.c, paciente=self.p, medico=self.medico, status='aberto', fc=199)
        r = self.client.get(self.url('medicoes'))
        self.assertContains(r, '120x80')
        self.assertNotContains(r, '199')
        self.assertNotContains(r, 'SEGREDO-CLINICO')
        self.assertNotContains(r, 'HIPOTESE-X')

    def test_aviso_vai_para_clinica(self):
        self.logar()
        ag = self.consulta()
        r = self.client.post(self.url('avisos'), {'tipo': 'atraso', 'agendamento': ag.pk, 'mensagem': 'Chego 10 min depois'})
        self.assertRedirects(r, self.url('avisos'), fetch_redirect_response=False)
        self.assertEqual(AvisoPaciente.objects.get().agendamento, ag)
        self.assertTrue(Lembrete.objects.filter(clinica=self.c, origem='app_paciente', mensagem='Chego 10 min depois').exists())

    def test_aviso_nao_aceita_consulta_alheia(self):
        self.logar()
        alheia = self.consulta(self.sem_app)
        self.client.post(self.url('avisos'), {'tipo': 'atraso', 'agendamento': alheia.pk, 'mensagem': 'x'})
        self.assertFalse(AvisoPaciente.objects.exists())

    def test_mensagens_nao_mostram_codigo_de_acesso(self):
        self.logar()
        ag = self.consulta()
        Notificacao.objects.create(clinica=self.c, canal='email', destinatario='m@e.com', mensagem='Lembrete da consulta',
                                   evento='lembrete', agendamento=ag, status='enviado')
        Notificacao.objects.create(clinica=self.c, canal='whatsapp', destinatario='55', mensagem='Lembrete da consulta',
                                   evento='lembrete', agendamento=ag, status='enviado')
        Notificacao.objects.create(clinica=self.c, canal='email', destinatario='m@e.com', mensagem='codigo 123456',
                                   evento='portal_codigo', status='enviado')
        r = self.client.get(self.url('avisos'))
        self.assertContains(r, 'Lembrete da consulta', count=1)
        self.assertNotContains(r, 'codigo 123456')

    def test_manifest_publico_com_escopo_da_clinica(self):
        d = self.client.get(self.url('manifest')).json()
        self.assertEqual(d['scope'], self.url('inicio'))

    def test_sair_exige_post(self):
        self.logar()
        self.assertEqual(self.client.get(self.url('sair')).status_code, 405)
        self.client.post(self.url('sair'))
        self.assertRedirects(self.client.get(self.url('inicio')), self.url('entrar'), fetch_redirect_response=False)

    def _dados_form(self, **kw):
        return {'nome': 'Novo', 'sexo': '', 'uf': '', 'origem': '', 'ativo': 'on', 'acesso_app': 'on', **kw}

    def test_cadastro_exige_dados_para_liberar_app(self):
        f = PacienteForm(self._dados_form(), clinica=self.c)
        self.assertFalse(f.is_valid())
        self.assertTrue({'cpf', 'data_nascimento', 'celular'} <= set(f.errors))
        f = PacienteForm(self._dados_form(cpf='111.222.333-44', data_nascimento='1990-01-01', celular='11999990000'),
                         clinica=self.c)
        self.assertTrue(f.is_valid(), f.errors)

    def test_cadastro_recusa_cpf_duplicado_no_app(self):
        f = PacienteForm(self._dados_form(cpf='12345678909', data_nascimento='1980-05-10', celular='11999990000'),
                         clinica=self.c)
        self.assertFalse(f.is_valid())
        self.assertIn('cpf', f.errors)
