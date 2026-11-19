# MedAccess — Gestão de Clínicas (PWA, multi-clínica)

Sistema web instalável (PWA) em Django para clínicas e consultórios: agenda, marcação online, prontuário
eletrônico, prescrições, financeiro, estoque, pacotes de sessões, call center, campanhas, relatórios e BI.

## Como rodar

```bat
pip install -r requirements.txt
python manage.py migrate
python manage.py popular_demo        :: dados de demonstração (opcional)
iniciar.bat                          :: ou: python manage.py runserver
```

Acesse `http://localhost:8000`. Logins de demonstração (senha `admin123`):

| Login | Perfil |
|---|---|
| `admin` | superusuário (todas as clínicas) |
| `recepcao` | recepção (sem acesso ao prontuário) |
| `financeiro` | financeiro / estoque |
| `dra.ana` | médica — prontuário **consulta e registro** |
| `dr.bruno` | fisioterapeuta — prontuário **somente consulta** |

(Na 2ª clínica os mesmos logins terminam com `2`, ex.: `recepcao2`.)

## Configuração (`.env`)

Edite o `.env` (modelo em `.env.example`): `SITE_URL` (URL pública usada nos links enviados aos pacientes),
SMTP de e-mail, `DJANGO_DEBUG=0` em produção, etc. O WhatsApp é configurado **por clínica** em
*Administrativo › Configurações da clínica* — as mensagens saem do número de WhatsApp cadastrado na clínica
(Evolution API, Z-API, WhatsApp Cloud API da Meta, webhook próprio ou modo simulado com link wa.me).

## Tarefas agendadas (já criadas neste computador)

No Agendador de Tarefas do Windows, pasta **MedAccess**, rodando sem janela via `pythonw executar_tarefa.py`:

- **Lembretes** — a cada 10 min (lembretes 24h antes, agenda diária dos médicos, aniversários, alertas)
- **Backup** — todo dia às 12:00 (`backups\`, mantém os 30 últimos)

O resultado fica em `logs\tarefas.log`. Para rodar manualmente: `tarefas_agendadas.bat [backup]`.

## Publicação com HTTPS (servidor)

Mesmo padrão do projeto Site: Django em `127.0.0.1:18003` atrás do Caddy.

1. Copie o projeto para `C:\webapps\clinica`, crie o `venv` e instale o `requirements.txt`.
2. Crie o `.env` a partir de `.env.producao.example` (com `SITE_URL=https://...` e `DJANGO_DEBUG=0`).
3. Cole os blocos de `deploy\caddy\clinica.caddy` no `C:\webapps\caddy\Caddyfile` (crie o DNS `clinica` na Cloudflare
   ou use o acesso por IP na porta 8003) e recarregue o Caddy.
4. Inicie com `deploy\iniciar_clinica.bat`. Com HTTPS, o botão **Instalar app** (PWA) aparece nos navegadores.

## Integrações (configuração por clínica, em Configurações da clínica)

- **WhatsApp**: Evolution API (QR Code direto no sistema em *WhatsApp e e-mails › Conectar WhatsApp*), Z-API,
  WhatsApp Cloud API (Meta) ou webhook. Mensagens saem do número da clínica.
- **E-mail**: SMTP próprio da clínica (ex.: Gmail com senha de app) ou o do `.env`.
- **SMS**: Twilio, Zenvia ou webhook.
- **Teleconsulta**: Jitsi Meet. Para uso profissional, use um servidor Jitsi próprio (o meet.jit.si limita salas
  incorporadas). O paciente aceita o termo (CFM 2.314/2022) e pode autorizar a gravação, que o médico faz pelo navegador
  e fica salva no prontuário.

## Módulos

- **Banco**: PostgreSQL (configurado no `.env`: `DB_ENGINE`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`). Primeira vez: `configurar_postgres.bat` (cria o banco, migra e copia os dados do SQLite). O backup diário usa `pg_dump`.
- **Multi-clínica**: cada clínica com seus dados, usuários e perfis de acesso (permissão por módulo: sem acesso / ver / editar).
- **Marcação de consulta**: tela da recepção e página pública para o paciente (especialidade › médico com grade › tipo › horário livre), grade de horários de todos os médicos, bloqueios, lista de espera.
- **Agenda**: calendário dia/semana/mês por profissional, agenda do dia com confirmação de presença, chegada e atendimento; confirmação/cancelamento pelo paciente via link; check-in digital com consentimento LGPD; teleconsulta (Jitsi).
- **Prontuário eletrônico**: histórico clínico, atendimentos SOAP com sinais vitais/IMC, **modelos por especialidade** (campos próprios e textos padrão), CID-10/CID-11, assinatura (bloqueio após finalizar + adendos), exames/anexos privados, **comparativo e gráfico de exames laboratoriais** com faixas de referência, teleconsulta com gravação autorizada, linha do tempo, impressão e auditoria de acessos. Acesso do médico parametrizado no cadastro do médico (não acessa / somente consulta / consulta e registro).
- **Documentos**: receitas com **checagem de interações medicamentosas** (inclui os medicamentos de uso contínuo) e alerta de alergia, link para o **Bulário ANVISA**, receita de controle especial, atestados, declarações, pedidos de exame, modelos com variáveis.
- **Tabelas**: medicamentos com importação **CMED/ANVISA** (PF/PMC por alíquota de ICMS), procedimentos **SUS/SIGTAP** (ZIP oficial) e TUSS/CSV, **CID-10** (DATASUS) e **CID-11** (OMS), interações medicamentosas (base inicial + CSV), tabela de preços.
- **Pacotes de sessões**: venda de N sessões, parcelamento no financeiro, consumo automático e saldo.
- **Financeiro**: contas a pagar/receber, baixa, fluxo de caixa, **conciliação bancária** (extrato OFX/CSV, casamento automático), repasse médico com taxas de cartão.
- **Estoque**: produtos, lotes e validade, kardex, baixa automática de insumos por atendimento (rastreio por paciente).
- **Relacionamento**: WhatsApp/e-mail automáticos, call center pós-consulta/faltas/retornos, NPS, aniversários, campanhas segmentadas.
- **Relatórios/BI**: ocupação, faltas, ticket médio, origem dos pacientes, faturamento por convênio, NPS e outros, com exportação CSV.

## Enviar para o GitHub

`subir_github.bat` (envia para `https://github.com/seculus-2023/clinica_med.git`). O `.env`, o banco e os
arquivos de pacientes ficam fora do repositório pelo `.gitignore`.
