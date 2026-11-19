from .models import MODULOS, Perfil

PERFIS_PADRAO = {
    'Administrador': ({m: 'editar' for m, _ in MODULOS}, False, 'Acesso total à clínica'),
    'Recepção': ({'dashboard': 'ver', 'agenda': 'editar', 'cadastros': 'editar', 'sessoes': 'editar',
                  'estoque': 'ver', 'financeiro': 'ver', 'convenios': 'ver', 'prontuario': 'nenhum', 'documentos': 'ver', 'callcenter': 'editar',
                  'relatorios': 'ver', 'administrativo': 'nenhum'}, False, 'Agenda, cadastros e atendimento'),
    'Médico': ({'dashboard': 'ver', 'agenda': 'editar', 'cadastros': 'ver', 'sessoes': 'ver',
                'estoque': 'ver', 'financeiro': 'nenhum', 'prontuario': 'ver', 'documentos': 'editar', 'callcenter': 'ver',
                'relatorios': 'ver', 'administrativo': 'nenhum'}, True, 'Própria agenda, prescrições e documentos'),
    'Financeiro': ({'dashboard': 'ver', 'agenda': 'ver', 'cadastros': 'ver', 'sessoes': 'editar',
                    'estoque': 'editar', 'financeiro': 'editar', 'convenios': 'editar', 'prontuario': 'nenhum', 'documentos': 'nenhum', 'callcenter': 'ver',
                    'relatorios': 'ver', 'administrativo': 'nenhum'}, False, 'Financeiro, estoque e pacotes'),
    'Call center': ({'dashboard': 'ver', 'agenda': 'editar', 'cadastros': 'ver', 'sessoes': 'ver',
                     'estoque': 'nenhum', 'financeiro': 'nenhum', 'prontuario': 'nenhum', 'documentos': 'nenhum', 'callcenter': 'editar',
                     'relatorios': 'nenhum', 'administrativo': 'nenhum'}, False, 'Contato com pacientes'),
}


def preparar_clinica(clinica):
    """Perfis de acesso, modelos de prontuário e catálogo de exames para uma clínica nova."""
    from prontuario.padroes import criar_exames_padrao, criar_modelos_padrao
    perfis = criar_perfis_padrao(clinica)
    criar_modelos_padrao(clinica)
    criar_exames_padrao(clinica)
    from prontuario.termos import criar_termos_padrao
    criar_termos_padrao(clinica)
    return perfis


def criar_perfis_padrao(clinica):
    criados = {}
    for nome, (perms, propria, desc) in PERFIS_PADRAO.items():
        p, _ = Perfil.objects.get_or_create(
            clinica=clinica, nome=nome,
            defaults={'permissoes': perms, 'apenas_propria_agenda': propria, 'descricao': desc})
        criados[nome] = p
    return criados
