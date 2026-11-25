from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from agenda.models import Agendamento, AvaliacaoNPS
from cadastros.models import Medico, Paciente, TipoAtendimento
from contas.models import Clinica, Lembrete, Perfil, Usuario, Vinculo

from . import services
from .models import Andamento, Manifestacao, Setor
from .services import ErroOuvidoria


@mock.patch('notificacoes.services._despachar', lambda ids: None)
class OuvidoriaTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.clinica = Clinica.objects.create(nome='Clínica Teste')
        cls.outra = Clinica.objects.create(nome='Outra')
        cls.config = services.garantir_config(cls.clinica)
        cls.setor = Setor.objects.get(clinica=cls.clinica, nome='Recepção')
        ouv = Perfil.objects.create(clinica=cls.clinica, nome='Ouvidoria', permissoes={'ouvidoria': 'editar'})
        leitura = Perfil.objects.create(clinica=cls.clinica, nome='Leitura', permissoes={'ouvidoria': 'ver'})
        recep = Perfil.objects.create(clinica=cls.clinica, nome='Recepção', permissoes={'agenda': 'editar'})
        cls.ouvidor = Usuario.objects.create_user('ouvidor', password='x')
        cls.leitor = Usuario.objects.create_user('leitor', password='x')
        cls.recep = Usuario.objects.create_user('recep', password='x')
        cls.gerente = Usuario.objects.create_user('gerente', password='x')
        Vinculo.objects.create(usuario=cls.ouvidor, clinica=cls.clinica, perfil=ouv)
        Vinculo.objects.create(usuario=cls.leitor, clinica=cls.clinica, perfil=leitura)
        Vinculo.objects.create(usuario=cls.recep, clinica=cls.clinica, perfil=recep)
        Vinculo.objects.create(usuario=cls.gerente, clinica=cls.clinica, perfil=recep)
        cls.paciente = Paciente.objects.create(clinica=cls.clinica, nome='Maria Reclamante', celular='11999998888',
                                               email='maria@exemplo.com')
        cls.medico = Medico.objects.create(clinica=cls.clinica, nome='Dra. Ana')
        cls.tipo = TipoAtendimento.objects.create(clinica=cls.clinica, nome='Consulta', duracao_minutos=30)

    def entrar(self, usuario):
        self.client.force_login(usuario)
        s = self.client.session
        s['clinica_id'] = self.clinica.pk
        s.save()

    def nova(self, **kw):
        kw.setdefault('tipo', 'reclamacao')
        kw.setdefault('assunto', 'Demora na recepção')
        kw.setdefault('descricao', 'Esperei 1 hora.')
        kw.setdefault('canal', 'presencial')
        return services.registrar(self.clinica, **kw)

    # ------------------------------------------------------------------ regras
    def test_protocolo_sequencial_por_clinica_e_ano(self):
        services.garantir_config(self.outra)
        a, _ = self.nova()
        b, _ = self.nova()
        c, _ = services.registrar(self.outra, tipo='elogio', assunto='x', descricao='y', canal='site')
        ano = timezone.localdate().year
        self.assertEqual((a.protocolo, b.protocolo, c.protocolo), (f'{ano}-00001', f'{ano}-00002', f'{ano}-00001'))
        self.assertEqual(a.prazo, timezone.localdate() + timedelta(days=self.config.prazo_dias))

    def test_chave_guardada_so_como_hash(self):
        m, chave = self.nova()
        self.assertNotIn(chave.replace('-', ''), m.chave_hash)
        self.assertEqual(m.chave_hash, services.hash_chave(chave.lower()))

    def test_anonima_descarta_identidade(self):
        m, _ = self.nova(anonima=True, nome='Fulano', telefone='11988887777', paciente=self.paciente)
        self.assertEqual((m.nome, m.telefone, m.paciente), ('', '', None))
        self.assertFalse(m.aceita_contato)

    def test_denuncia_prioridade_alta_e_paciente_preenche_contato(self):
        m, _ = self.nova(tipo='denuncia', paciente=self.paciente)
        self.assertEqual(m.prioridade, 1)
        self.assertEqual((m.nome, m.telefone, m.relacao), ('Maria Reclamante', '11999998888', 'paciente'))

    def test_registro_avisa_manifestante_e_alerta_equipe(self):
        from notificacoes.models import Notificacao
        m, chave = self.nova(paciente=self.paciente)
        avisos = Notificacao.objects.filter(clinica=self.clinica, evento='ouvidoria')
        self.assertTrue(avisos.exists())
        self.assertTrue(all(m.protocolo in n.mensagem and chave in n.mensagem for n in avisos))
        alerta = Lembrete.objects.filter(clinica=self.clinica, origem='ouvidoria')
        self.assertEqual(list(alerta.values_list('usuario', flat=True)), [self.ouvidor.pk])
        self.assertNotIn('Maria', alerta.first().titulo)

    def test_fluxo_encaminhar_parecer_responder_avaliar(self):
        m, _ = self.nova(paciente=self.paciente)
        with self.assertRaises(ErroOuvidoria):
            services.encaminhar(m, self.ouvidor, None, self.setor, 'sem responsável')
        services.encaminhar(m, self.ouvidor, self.gerente, self.setor, 'Apurar')
        self.assertEqual((m.status, m.responsavel), ('encaminhada', self.gerente))
        self.assertTrue(Lembrete.objects.filter(usuario=self.gerente, origem='ouvidoria').exists())
        services.parecer(m, self.gerente, 'Fila cheia no dia.')
        self.assertEqual(m.status, 'em_analise')
        services.responder(m, self.ouvidor, 'Reforçamos a equipe.')
        self.assertEqual(m.status, 'respondida')
        self.assertIsNotNone(m.primeira_resposta_em)
        services.avaliar(m, False, 2, 'Não resolveu')
        m.refresh_from_db()
        self.assertEqual((m.status, m.avaliacao_nota), ('concluida', 2))
        with self.assertRaises(ErroOuvidoria):
            services.avaliar(m, True, 5)
        self.assertTrue(Lembrete.objects.filter(titulo__contains='avaliação negativa').exists())

    def test_prorrogacao_unica_e_limitada(self):
        m, _ = self.nova()
        with self.assertRaises(ErroOuvidoria):
            services.prorrogar(m, self.ouvidor, self.config.prorrogacao_dias + 1, 'x')
        prazo = m.prazo
        services.prorrogar(m, self.ouvidor, 5, 'Aguardando setor')
        self.assertEqual(m.prazo, prazo + timedelta(days=5))
        with self.assertRaises(ErroOuvidoria):
            services.prorrogar(m, self.ouvidor, 1, 'de novo')

    def test_mensagem_do_manifestante_reabre_respondida(self):
        m, _ = self.nova()
        services.responder(m, self.ouvidor, 'Resposta', concluir=True, conclusao='procedente')
        self.assertEqual(m.status, 'concluida')
        services.mensagem_manifestante(m, 'Continua acontecendo')
        m.refresh_from_db()
        self.assertEqual((m.status, m.conclusao), ('em_analise', ''))
        services.arquivar(m, self.ouvidor, 'duplicada')
        with self.assertRaises(ErroOuvidoria):
            services.mensagem_manifestante(m, 'oi')

    def test_rotina_alerta_vencidas_e_conclui_sem_retorno(self):
        vencida, _ = self.nova()
        Manifestacao.objects.filter(pk=vencida.pk).update(prazo=timezone.localdate() - timedelta(days=1))
        resp, _ = self.nova()
        services.responder(resp, self.ouvidor, 'ok')
        Manifestacao.objects.filter(pk=resp.pk).update(respondida_em=timezone.now() - timedelta(days=30))
        services.rotina_diaria(self.clinica)
        services.rotina_diaria(self.clinica)
        self.assertEqual(Lembrete.objects.filter(origem='ouvidoria_prazo', usuario=self.ouvidor).count(), 1)
        resp.refresh_from_db()
        self.assertEqual((resp.status, resp.conclusao), ('concluida', 'atendida'))

    def test_nps_detrator_com_comentario_abre_reclamacao(self):
        ag = Agendamento.objects.create(clinica=self.clinica, paciente=self.paciente, medico=self.medico,
                                        tipo=self.tipo, inicio=timezone.now() - timedelta(hours=2), notificar=False,
                                        status='concluido')
        av = AvaliacaoNPS.objects.create(clinica=self.clinica, agendamento=ag, nota=3, comentario='Atrasou muito')
        m = services.abrir_por_nps(av)
        self.assertEqual((m.canal, m.tipo, m.paciente, m.agendamento), ('nps', 'reclamacao', self.paciente, ag))
        av2 = AvaliacaoNPS(clinica=self.clinica, agendamento=ag, nota=3, comentario='')
        self.assertIsNone(services.abrir_por_nps(av2))

    # ------------------------------------------------------------------ telas e permissões
    def test_painel_exige_modulo_ou_mostra_so_as_do_usuario(self):
        m, _ = self.nova(assunto='Assunto secreto')
        self.entrar(self.recep)
        r = self.client.get(reverse('ouvidoria:painel'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Assunto secreto')
        self.assertEqual(self.client.get(reverse('ouvidoria:detalhe', args=[m.pk])).status_code, 404)
        services.encaminhar(m, self.ouvidor, self.recep, None, 'Veja isto')
        self.assertContains(self.client.get(reverse('ouvidoria:painel')), 'Assunto secreto')
        r = self.client.post(reverse('ouvidoria:acao', args=[m.pk, 'responder']), {'resp-texto': 'x'})
        self.assertEqual(r.status_code, 403)
        self.client.post(reverse('ouvidoria:acao', args=[m.pk, 'parecer']), {'par-texto': 'Apurado'})
        self.assertTrue(m.andamentos.filter(tipo='parecer', usuario=self.recep).exists())

    def test_sigilo_esconde_identidade_de_quem_nao_edita(self):
        m, _ = self.nova(nome='Joana Sigilosa', telefone='11977776666', sigilosa=True)
        self.entrar(self.leitor)
        r = self.client.get(reverse('ouvidoria:detalhe', args=[m.pk]))
        self.assertNotContains(r, 'Joana Sigilosa')
        self.assertNotContains(r, '11977776666')
        self.entrar(self.ouvidor)
        self.assertContains(self.client.get(reverse('ouvidoria:detalhe', args=[m.pk])), 'Joana Sigilosa')

    def test_setor_designado_nao_ve_notas_internas(self):
        m, _ = self.nova()
        services.nota(m, self.ouvidor, 'Nota reservada da ouvidoria')
        services.encaminhar(m, self.ouvidor, self.recep, None, 'Apurar')
        self.entrar(self.recep)
        self.assertNotContains(self.client.get(reverse('ouvidoria:detalhe', args=[m.pk])), 'Nota reservada')

    def test_qualquer_usuario_registra_e_recebe_comprovante(self):
        self.entrar(self.recep)
        r = self.client.post(reverse('ouvidoria:nova'), {
            'tipo': 'elogio', 'canal': 'telefone', 'prioridade': 2, 'assunto': 'Ótimo atendimento',
            'descricao': 'Equipe atenciosa', 'nome': 'João', 'telefone': '11966665555', 'aceita_contato': 'on'})
        m = Manifestacao.objects.get(assunto='Ótimo atendimento')
        self.assertRedirects(r, reverse('ouvidoria:comprovante', args=[m.pk]))
        r = self.client.get(reverse('ouvidoria:comprovante', args=[m.pk]))
        self.assertContains(r, m.protocolo)
        self.assertEqual(m.registrada_por, self.recep)

    def test_outra_clinica_nao_acessa(self):
        m, _ = self.nova()
        outro = Usuario.objects.create_user('outro', password='x')
        perfil = Perfil.objects.create(clinica=self.outra, nome='Adm', permissoes={'ouvidoria': 'editar'})
        Vinculo.objects.create(usuario=outro, clinica=self.outra, perfil=perfil)
        self.client.force_login(outro)
        s = self.client.session
        s['clinica_id'] = self.outra.pk
        s.save()
        self.assertEqual(self.client.get(reverse('ouvidoria:detalhe', args=[m.pk])).status_code, 404)

    # ------------------------------------------------------------------ páginas públicas
    def dados_publicos(self, **kw):
        d = {'tipo': 'sugestao', 'assunto': 'Mais cadeiras', 'descricao': 'A sala de espera é pequena.',
             'nome': 'Carla', 'telefone': '11955554444', 'lgpd': 'on'}
        d.update(kw)
        return d

    def test_formulario_publico_registra_e_mostra_chave_uma_vez(self):
        url = reverse('ouvidoria:publico', args=[self.clinica.codigo_publico])
        r = self.client.post(url, self.dados_publicos())
        self.assertRedirects(r, reverse('ouvidoria:registrada', args=[self.clinica.codigo_publico]),
                             fetch_redirect_response=False)
        m = Manifestacao.objects.get(assunto='Mais cadeiras')
        self.assertEqual(m.canal, 'site')
        r = self.client.get(reverse('ouvidoria:registrada', args=[self.clinica.codigo_publico]))
        self.assertContains(r, m.protocolo)
        r = self.client.get(reverse('ouvidoria:registrada', args=[self.clinica.codigo_publico]))
        self.assertEqual(r.status_code, 302)

    def test_formulario_publico_exige_contato_ou_anonimo(self):
        url = reverse('ouvidoria:publico', args=[self.clinica.codigo_publico])
        r = self.client.post(url, self.dados_publicos(telefone='', email=''))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Manifestacao.objects.exists())
        self.client.post(url, self.dados_publicos(nome='', telefone='', anonima='on'))
        self.assertTrue(Manifestacao.objects.get().anonima)

    def test_honeypot_e_limite_por_sessao(self):
        url = reverse('ouvidoria:publico', args=[self.clinica.codigo_publico])
        self.client.post(url, self.dados_publicos(site='robo'))
        self.assertFalse(Manifestacao.objects.exists())
        for _ in range(7):
            self.client.post(url, self.dados_publicos())
        self.assertEqual(Manifestacao.objects.count(), 5)

    def test_consulta_por_protocolo_e_chave(self):
        m, chave = self.nova()
        url = reverse('ouvidoria:consultar', args=[self.clinica.codigo_publico])
        r = self.client.post(url, {'protocolo': m.protocolo, 'chave': 'ERRADA00'})
        self.assertContains(r, 'não conferem')
        r = self.client.post(url, {'protocolo': m.protocolo, 'chave': chave.lower()})
        self.assertRedirects(r, reverse('ouvidoria:acompanhar', args=[m.token]))

    def test_acompanhamento_publico_oculta_internos_e_aceita_avaliacao(self):
        m, _ = self.nova()
        services.nota(m, self.ouvidor, 'Nota interna confidencial')
        services.responder(m, self.ouvidor, 'Resposta oficial ao paciente')
        url = reverse('ouvidoria:acompanhar', args=[m.token])
        r = self.client.get(url)
        self.assertContains(r, 'Resposta oficial ao paciente')
        self.assertNotContains(r, 'Nota interna confidencial')
        self.client.post(url, {'acao': 'avaliar', 'resolvida': '1', 'nota': '5'})
        m.refresh_from_db()
        self.assertEqual((m.status, m.avaliacao_resolvida, m.avaliacao_nota), ('concluida', True, 5))
        self.client.post(url, {'acao': 'mensagem', 'texto': 'Obrigada!'})
        self.assertTrue(Andamento.objects.filter(manifestacao=m, tipo='manifestante').exists())

    def test_telas_internas_renderizam(self):
        m, _ = self.nova(paciente=self.paciente)
        self.nova(paciente=self.paciente, tipo='elogio')
        self.entrar(self.ouvidor)
        for url in (reverse('ouvidoria:painel'), reverse('ouvidoria:painel') + '?aba=todas&tipo=reclamacao',
                    reverse('ouvidoria:detalhe', args=[m.pk]), reverse('ouvidoria:configurar'),
                    reverse('ouvidoria:nova'), reverse('ouvidoria:setor_list')):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        r = self.client.post(reverse('ouvidoria:acao', args=[m.pk, 'responder']),
                             {'resp-texto': 'Resolvido', 'resp-concluir': 'on', 'resp-conclusao': 'procedente'})
        self.assertRedirects(r, reverse('ouvidoria:detalhe', args=[m.pk]))
        m.refresh_from_db()
        self.assertEqual((m.status, m.conclusao), ('concluida', 'procedente'))
        self.assertContains(self.client.get(reverse('ouvidoria:detalhe', args=[m.pk])), 'Reabrir')

    def test_relatorio_sem_nome_do_manifestante(self):
        self.nova(paciente=self.paciente)
        Perfil.objects.filter(nome='Ouvidoria').update(permissoes={'ouvidoria': 'editar', 'relatorios': 'ver'})
        self.entrar(self.ouvidor)
        r = self.client.get(reverse('painel:relatorios') + '?tipo=ouvidoria')
        self.assertContains(r, 'Demora na recepção')
        self.assertNotContains(r, 'Maria Reclamante')

    def test_app_do_paciente_registra_e_lista(self):
        Paciente.objects.filter(pk=self.paciente.pk).update(acesso_app=True, consentimento_lgpd_em=timezone.now())
        s = self.client.session
        s['portal'] = {'clinica': self.clinica.pk, 'paciente': self.paciente.pk,
                       'expira': (timezone.now() + timedelta(hours=1)).timestamp()}
        s.save()
        url = reverse('portal:ouvidoria', args=[self.clinica.codigo_publico])
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.post(url, {'tipo': 'solicitacao', 'assunto': 'Segunda via de laudo', 'descricao': 'Preciso.'})
        m = Manifestacao.objects.get(assunto='Segunda via de laudo')
        self.assertEqual((m.canal, m.paciente, m.nome), ('app', self.paciente, 'Maria Reclamante'))
        self.assertContains(self.client.get(url), m.protocolo)

    def test_formulario_publico_desativado(self):
        self.config.formulario_publico = False
        self.config.save()
        url = reverse('ouvidoria:publico', args=[self.clinica.codigo_publico])
        r = self.client.post(url, self.dados_publicos())
        self.assertContains(r, 'indisponível')
        self.assertFalse(Manifestacao.objects.exists())
