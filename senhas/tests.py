from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento
from agenda.services import mudar_status
from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.models import Clinica, Perfil, Usuario, Vinculo

from . import services
from .models import ChamadaSenha, PontoAtendimento, Senha, ServicoSenha
from .services import ErroSenha


class SenhasTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clinica = Clinica.objects.create(nome='Clínica Teste')
        cls.outra = Clinica.objects.create(nome='Outra')
        cls.config = services.garantir_padroes(cls.clinica)
        cls.config_outra = services.garantir_padroes(cls.outra)
        cls.servico = ServicoSenha.objects.get(clinica=cls.clinica, prefixo='A')
        cls.ponto = PontoAtendimento.objects.get(clinica=cls.clinica, nome='Guichê 1')
        cls.ponto2 = PontoAtendimento.objects.get(clinica=cls.clinica, nome='Guichê 2')
        perfil = Perfil.objects.create(clinica=cls.clinica, nome='Recepção', permissoes={'agenda': 'editar'})
        leitura = Perfil.objects.create(clinica=cls.clinica, nome='Leitura', permissoes={'agenda': 'ver'})
        cls.user = Usuario.objects.create_user('recep', password='senha123')
        cls.leitor = Usuario.objects.create_user('leitor', password='senha123')
        cls.user2 = Usuario.objects.create_user('recep2', password='senha123')
        cls.intruso = Usuario.objects.create_user('intruso', password='senha123')
        cls.gestor = Usuario.objects.create_user('gestor', password='senha123')
        adm = Perfil.objects.create(clinica=cls.clinica, nome='Adm',
                                    permissoes={'agenda': 'editar', 'administrativo': 'editar', 'relatorios': 'ver'})
        Vinculo.objects.create(usuario=cls.user2, clinica=cls.clinica, perfil=perfil)
        Vinculo.objects.create(usuario=cls.intruso, clinica=cls.clinica, perfil=perfil)
        Vinculo.objects.create(usuario=cls.gestor, clinica=cls.clinica, perfil=adm)
        cls.ponto.responsaveis.add(cls.user, cls.user2)
        cls.ponto2.responsaveis.add(cls.user, cls.user2)
        Vinculo.objects.create(usuario=cls.user, clinica=cls.clinica, perfil=perfil)
        Vinculo.objects.create(usuario=cls.leitor, clinica=cls.clinica, perfil=leitura)
        cls.medico = Medico.objects.create(clinica=cls.clinica, nome='Dra. Ana')
        cls.tipo = TipoAtendimento.objects.create(clinica=cls.clinica, nome='Consulta', duracao_minutos=30)
        cls.paciente = Paciente.objects.create(clinica=cls.clinica, nome='Carlos Sigiloso')

    def agendamento(self, **kw):
        kw.setdefault('inicio', timezone.localtime().replace(hour=12, minute=0, second=0, microsecond=0))
        return Agendamento.objects.create(clinica=self.clinica, paciente=kw.pop('paciente', self.paciente),
                                          medico=self.medico, tipo=self.tipo, notificar=False, **kw)

    def entrar(self, usuario=None):
        self.client.force_login(usuario or self.user)
        s = self.client.session
        s['clinica_id'] = self.clinica.pk
        s.save()

    def chamar(self, ponto=None, usuario=None):
        ponto, usuario = ponto or self.ponto, usuario or self.user
        services.assumir_guiche(self.clinica, ponto, usuario)
        return services.chamar_proxima(self.clinica, ponto, usuario)

    def test_numeracao_e_codigo(self):
        self.assertEqual(services.emitir(self.clinica, self.servico).codigo, 'A001')
        self.assertEqual(services.emitir(self.clinica, self.servico).codigo, 'A002')
        self.assertEqual(services.emitir(self.clinica, self.servico, True).codigo, 'AP001')

    def test_preferencial_e_chamada_primeiro(self):
        services.emitir(self.clinica, self.servico)
        pref = services.emitir(self.clinica, self.servico, True)
        self.assertEqual(self.chamar().pk, pref.pk)

    def test_guiche_ocupado_nao_chama_outra(self):
        services.emitir(self.clinica, self.servico)
        services.emitir(self.clinica, self.servico)
        self.chamar()
        with self.assertRaises(ErroSenha):
            self.chamar()
        self.assertEqual(self.chamar(self.ponto2, self.user2).codigo, 'A002')

    def test_senha_de_ontem_nao_entra_na_fila(self):
        s = services.emitir(self.clinica, self.servico)
        Senha.objects.filter(pk=s.pk).update(data=s.data - timedelta(days=1))
        with self.assertRaises(ErroSenha):
            self.chamar()

    def test_rechamar_gera_novo_evento_de_voz(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        services.rechamar(s, self.user)
        self.assertEqual(ChamadaSenha.objects.filter(senha=s).count(), 2)
        self.assertEqual(ChamadaSenha.objects.filter(senha=s).first().texto, 'Senha á, 1. Guichê 1.')

    def test_transicao_invalida(self):
        s = services.emitir(self.clinica, self.servico)
        with self.assertRaises(ErroSenha):
            services.aplicar_acao(s, 'concluir', self.user)

    def test_ausente_volta_para_fila(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        services.aplicar_acao(s, 'ausente', self.user)
        s = services.aplicar_acao(s, 'devolver', self.user)
        self.assertEqual((s.status, s.ponto, s.local), ('aguardando', None, ''))

    def test_senha_do_agendamento_e_unica_e_marca_chegada(self):
        ag = self.agendamento()
        s1, criada1 = services.emitir_para_agendamento(ag)
        s2, criada2 = services.emitir_para_agendamento(ag)
        ag.refresh_from_db()
        self.assertEqual((s1.pk, criada1, criada2, ag.status), (s2.pk, True, False, 'aguardando'))
        self.assertIsNotNone(ag.chegada_em)

    def test_idoso_recebe_preferencial(self):
        hoje = timezone.localdate()
        idoso = Paciente.objects.create(clinica=self.clinica, nome='Idoso',
                                        data_nascimento=hoje.replace(year=hoje.year - 70, day=1))
        s, _ = services.emitir_para_agendamento(self.agendamento(paciente=idoso))
        self.assertTrue(s.preferencial)

    def test_agendamento_de_outro_dia_nao_recebe_senha(self):
        ag = self.agendamento(inicio=timezone.now() + timedelta(days=3))
        with self.assertRaises(ErroSenha):
            services.emitir_para_agendamento(ag)

    def test_medico_chama_e_status_sincroniza(self):
        ag = self.agendamento(status='aguardando')
        s = services.chamar_agendamento(ag)
        self.assertEqual((s.status, s.local), ('chamada', 'Dra. Ana'))
        mudar_status(ag, 'em_atendimento')
        s.refresh_from_db()
        self.assertEqual(s.status, 'em_atendimento')
        mudar_status(ag, 'concluido')
        s.refresh_from_db()
        self.assertEqual(s.status, 'concluida')

    def test_tv_abre_sem_login_e_nao_expoe_paciente(self):
        ag = self.agendamento(status='aguardando')
        services.chamar_agendamento(ag)
        url = reverse('senhas:tv_dados', args=[self.config.token])
        r = self.client.get(url, {'desde': 0})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['atual']['codigo'], 'A001')
        self.assertEqual(len(r.json()['novas']), 1)
        self.assertNotContains(r, 'Sigiloso')
        self.assertEqual(self.client.get(reverse('senhas:tv', args=[self.config.token])).status_code, 200)

    def test_tv_nao_repete_chamada_antiga(self):
        services.emitir(self.clinica, self.servico)
        self.chamar()
        ChamadaSenha.objects.update(criado_em=timezone.now() - timedelta(minutes=5))
        self.assertEqual(services.dados_painel(self.config, 0)['novas'], [])

    def test_tv_isolada_por_clinica(self):
        services.emitir(self.clinica, self.servico)
        self.chamar()
        self.assertIsNone(services.dados_painel(self.config_outra, 0)['atual'])

    def test_novo_link_invalida_o_anterior(self):
        self.entrar()
        antigo = self.config.token
        self.client.post(reverse('senhas:novo_link'))
        self.assertEqual(self.client.get(reverse('senhas:tv', args=[antigo])).status_code, 404)

    def test_tela_e_fluxo_pela_web(self):
        self.entrar()
        self.assertNotContains(self.client.get(reverse('senhas:painel')), 'Chamar próxima')
        self.client.post(reverse('senhas:assumir_guiche', args=[self.ponto.pk]))
        self.assertContains(self.client.get(reverse('senhas:painel')), 'Chamar próxima')
        r = self.client.post(reverse('senhas:emitir'), {'servico': self.servico.pk, 'preferencial': '0'})
        self.assertEqual(r.status_code, 302)
        self.client.post(reverse('senhas:proxima'))
        s = Senha.objects.get(clinica=self.clinica)
        self.assertEqual(s.status, 'chamada')
        self.assertContains(self.client.get(reverse('senhas:ticket', args=[s.pk])), 'A001')

    def test_paginas_de_configuracao_abrem(self):
        self.entrar(self.gestor)
        for nome in ('senhas:configurar', 'senhas:servico_novo', 'senhas:ponto_novo', 'senhas:servico_list'):
            self.assertEqual(self.client.get(reverse(nome)).status_code, 200, nome)

    def test_prefixo_p_e_recusado(self):
        self.entrar()
        self.client.post(reverse('senhas:servico_novo'), {'nome': 'X', 'prefixo': 'p', 'ordem': 1, 'ativo': 'on'})
        self.assertFalse(ServicoSenha.objects.filter(clinica=self.clinica, nome='X').exists())

    def test_somente_leitura_nao_emite(self):
        self.entrar(self.leitor)
        r = self.client.post(reverse('senhas:emitir'), {'servico': self.servico.pk})
        self.assertEqual(r.status_code, 403)

    def test_nao_acessa_senha_de_outra_clinica(self):
        sv = ServicoSenha.objects.get(clinica=self.outra, prefixo='A')
        s = services.emitir(self.outra, sv)
        self.entrar()
        self.assertEqual(self.client.get(reverse('senhas:ticket', args=[s.pk])).status_code, 404)

    # ---- guichê e usuário responsável ----
    def test_usuario_nao_autorizado_nao_assume(self):
        with self.assertRaises(ErroSenha):
            services.assumir_guiche(self.clinica, self.ponto, self.intruso)

    def test_administrador_assume_qualquer_guiche(self):
        services.assumir_guiche(self.clinica, self.ponto, self.gestor)
        self.assertEqual(services.guiche_do_usuario(self.clinica, self.gestor).pk, self.ponto.pk)

    def test_dois_usuarios_nao_ocupam_o_mesmo_guiche(self):
        services.assumir_guiche(self.clinica, self.ponto, self.user)
        with self.assertRaises(ErroSenha):
            services.assumir_guiche(self.clinica, self.ponto, self.user2)

    def test_usuario_fica_em_um_guiche_por_vez(self):
        services.assumir_guiche(self.clinica, self.ponto, self.user)
        services.assumir_guiche(self.clinica, self.ponto2, self.user)
        self.ponto.refresh_from_db()
        self.assertIsNone(self.ponto.operador)

    def test_nao_troca_de_guiche_com_senha_em_andamento(self):
        services.emitir(self.clinica, self.servico)
        self.chamar()
        with self.assertRaises(ErroSenha):
            services.assumir_guiche(self.clinica, self.ponto2, self.user)
        with self.assertRaises(ErroSenha):
            services.sair_guiche(self.clinica, self.user)

    def test_nao_chama_sem_assumir(self):
        services.emitir(self.clinica, self.servico)
        with self.assertRaises(ErroSenha):
            services.chamar_proxima(self.clinica, self.ponto, self.user)

    def test_abertura_expira_no_dia_seguinte(self):
        services.assumir_guiche(self.clinica, self.ponto, self.user)
        PontoAtendimento.objects.filter(pk=self.ponto.pk).update(operador_desde=timezone.now() - timedelta(days=1))
        self.assertIsNone(services.guiche_do_usuario(self.clinica, self.user))
        services.assumir_guiche(self.clinica, self.ponto, self.user2)

    def test_outro_atendente_nao_mexe_na_senha(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        with self.assertRaises(ErroSenha):
            services.aplicar_acao(s, 'concluir', self.user2)
        with self.assertRaises(ErroSenha):
            services.rechamar(s, self.user2)

    def test_gestor_libera_e_novo_atendente_continua(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        with self.assertRaises(ErroSenha):
            services.liberar_guiche(self.clinica, self.ponto, self.user2)
        services.liberar_guiche(self.clinica, self.ponto, self.gestor)
        services.assumir_guiche(self.clinica, self.ponto, self.user2)
        self.assertEqual(services.aplicar_acao(s, 'concluir', self.user2).concluida_por, self.user2)

    def test_historico_de_quem_atendeu(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        services.aplicar_acao(s, 'iniciar', self.user)
        s = services.aplicar_acao(s, 'concluir', self.user)
        self.assertEqual((s.chamada_por, s.iniciada_por, s.concluida_por), (self.user, self.user, self.user))
        self.assertIsNotNone(s.tempo_guiche)
        self.assertEqual(ChamadaSenha.objects.get(senha=s).usuario, self.user)

    def test_logout_libera_guiche(self):
        self.entrar()
        self.client.post(reverse('senhas:assumir_guiche', args=[self.ponto.pk]))
        self.client.post(reverse('contas:logout'))
        self.ponto.refresh_from_db()
        self.assertIsNone(self.ponto.operador)

    def test_recepcao_nao_edita_autorizacoes(self):
        self.entrar()
        r = self.client.post(reverse('senhas:ponto_editar', args=[self.ponto.pk]),
                             {'nome': 'Guichê 1', 'ativo': 'on', 'responsaveis': [self.intruso.pk]})
        self.assertEqual(r.status_code, 403)

    def test_administrador_edita_autorizacoes(self):
        self.entrar(self.gestor)
        r = self.client.post(reverse('senhas:ponto_editar', args=[self.ponto.pk]),
                             {'nome': 'Guichê 1', 'ativo': 'on', 'responsaveis': [self.intruso.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(list(self.ponto.responsaveis.all()), [self.intruso])

    def test_relatorio_por_atendente(self):
        services.emitir(self.clinica, self.servico)
        s = self.chamar()
        services.aplicar_acao(s, 'concluir', self.user)
        self.entrar(self.gestor)
        r = self.client.get(reverse('painel:relatorios'), {'tipo': 'atendentes'})
        self.assertContains(r, 'recep')
        self.assertContains(r, 'Tempo médio')

    def test_botoes_na_agenda_do_dia(self):
        ag = self.agendamento()
        self.entrar()
        self.assertContains(self.client.get(reverse('agenda:dia')), reverse('senhas:agendamento_emitir', args=[ag.pk]))

    def test_imprimir_senha_na_agenda_do_dia(self):
        ag = self.agendamento()
        self.entrar()
        self.assertNotContains(self.client.get(reverse('agenda:dia')), 'Imprimir senha')
        senha, _ = services.emitir_para_agendamento(ag, self.user)
        url_ticket = reverse('senhas:ticket', args=[senha.pk])
        self.assertContains(self.client.get(reverse('agenda:dia')), url_ticket)
        r = self.client.get(url_ticket)
        self.assertContains(r, senha.codigo)
        self.assertNotContains(r, 'Sigiloso')

    def test_medico_chama_pelo_app(self):
        u = Usuario.objects.create_user('dra', password='senha123')
        perfil = Perfil.objects.create(clinica=self.clinica, nome='Médico', permissoes={'agenda': 'ver'})
        Vinculo.objects.create(usuario=u, clinica=self.clinica, perfil=perfil)
        med = Medico.objects.create(clinica=self.clinica, nome='Dra. Bia', usuario=u)
        ag = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=med, tipo=self.tipo,
                                        inicio=timezone.now(), status='aguardando', notificar=False)
        self.entrar(u)
        self.client.post(reverse('areamedica:chamar', args=[ag.pk]))
        self.assertEqual(Senha.objects.get(agendamento=ag).local, 'Dra. Bia')
