"""Configurações do sistema MedAccess - Gestão de Clínicas."""
import os
from pathlib import Path

from django.contrib.messages import constants as messages

BASE_DIR = Path(__file__).resolve().parent.parent


def _carregar_env(arquivo):
    """Carrega variáveis de um arquivo .env (CHAVE=valor). O .env sempre prevalece (inclusive sobre valores
    herdados de um runserver iniciado antes de o .env ser alterado)."""
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding='utf-8').splitlines():
        linha = linha.strip()
        if not linha or linha.startswith('#') or '=' not in linha:
            continue
        chave, valor = linha.split('=', 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in '"\'':
            valor = valor[1:-1]
        os.environ[chave.strip()] = valor


_carregar_env(BASE_DIR / '.env')


def env(nome, padrao=None):
    return os.environ.get(nome, padrao)


SECRET_KEY = env('DJANGO_SECRET_KEY', 'dev-inseguro-troque-em-producao-9f3k2l1m0n')
DEBUG = env('DJANGO_DEBUG', '1') == '1'
ALLOWED_HOSTS = env('DJANGO_ALLOWED_HOSTS', '*').split(',')
CSRF_TRUSTED_ORIGINS = [o for o in env('DJANGO_CSRF_TRUSTED_ORIGINS', '').split(',') if o]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.humanize',
    'django.forms',
    'contas',
    'cadastros',
    'agenda',
    'estoque',
    'financeiro',
    'prontuario',
    'convenios',
    'portal',
    'assinaturas',
    'documentos',
    'callcenter',
    'notificacoes',
    'areamedica',
    'senhas',
    'ouvidoria',
    'painel',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'contas.middleware.ClinicaMiddleware',
    'assinaturas.middleware.AssinaturaMiddleware',
    'notificacoes.middleware.AutoLembretesMiddleware',
]

ROOT_URLCONF = 'clinica.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'contas.context_processors.clinica',
            ],
        },
    },
]

FORM_RENDERER = 'django.forms.renderers.TemplatesSetting'

WSGI_APPLICATION = 'clinica.wsgi.application'

# ---- Banco de dados (configurado no .env) ----
# DB_ENGINE: postgresql (padrão), sqlite ou mysql
_DB_ENGINES = {
    'sqlite': 'django.db.backends.sqlite3',
    'postgresql': 'django.db.backends.postgresql',
    'postgres': 'django.db.backends.postgresql',
    'mysql': 'django.db.backends.mysql',
}
_db_engine = env('DB_ENGINE', 'postgresql').strip().lower()
if _db_engine not in _DB_ENGINES:
    raise ValueError(f'DB_ENGINE inválido no .env: "{_db_engine}". Use sqlite, postgresql ou mysql.')
if _db_engine == 'sqlite':
    _db_nome = env('DB_NAME', 'db.sqlite3')
    DATABASES = {'default': {
        'ENGINE': _DB_ENGINES['sqlite'],
        'NAME': _db_nome if Path(_db_nome).is_absolute() else BASE_DIR / _db_nome,
        'OPTIONS': {'timeout': int(env('DB_TIMEOUT', '20'))},
    }}
else:
    DATABASES = {'default': {
        'ENGINE': _DB_ENGINES[_db_engine],
        'NAME': env('DB_NAME', 'medaccess'),
        'USER': env('DB_USER', ''),
        'PASSWORD': env('DB_PASSWORD', ''),
        'HOST': env('DB_HOST', 'localhost'),
        'PORT': env('DB_PORT', '5432' if _db_engine.startswith('postgres') else '3306'),
        'CONN_MAX_AGE': int(env('DB_CONN_MAX_AGE', '60')),
    }}
    if _db_engine == 'mysql':
        DATABASES['default']['OPTIONS'] = {'charset': 'utf8mb4'}

AUTH_USER_MODEL = 'contas.Usuario'
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 6}},
]

LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Sao_Paulo'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

LOGIN_URL = 'contas:login'
LOGIN_REDIRECT_URL = 'contas:selecionar_clinica'
LOGOUT_REDIRECT_URL = 'contas:login'

MESSAGE_TAGS = {messages.ERROR: 'danger'}

# ---- E-mail (SMTP). Sem configuração, os e-mails são exibidos no console. ----
EMAIL_BACKEND = env('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST', 'localhost')
EMAIL_PORT = int(env('EMAIL_PORT', '587'))
EMAIL_HOST_USER = env('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = env('EMAIL_USE_TLS', '1') == '1'
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL', 'MedAccess <nao-responda@medaccess.local>')

# URL pública usada nos links de confirmação enviados aos pacientes
SITE_URL = env('SITE_URL', 'http://localhost:8000').rstrip('/')

# Processamento automático de lembretes (sem precisar de agendador do sistema)
AUTO_LEMBRETES = env('AUTO_LEMBRETES', '1') == '1'
AUTO_LEMBRETES_INTERVALO_MIN = int(env('AUTO_LEMBRETES_INTERVALO_MIN', '10'))
# Envio de notificações em segundo plano (thread). Desligado nos testes.
NOTIFICACOES_ASSINCRONAS = env('NOTIFICACOES_ASSINCRONAS', '1') == '1'

PWA_VERSAO = '1.1.0'

# ---- Venda do sistema para outras clínicas (SaaS) ----
SAAS_ATIVO = env('SAAS_ATIVO', '0') == '1'                 # ativa planos, limites, faturas e bloqueio
SAAS_CADASTRO_ABERTO = env('SAAS_CADASTRO_ABERTO', '0') == '1'   # página pública /assinatura/cadastro/
SAAS_NOME = env('SAAS_NOME', 'MedAccess')
SAAS_PIX_CHAVE = env('SAAS_PIX_CHAVE', '')                 # chave PIX que recebe as mensalidades
SAAS_PIX_NOME = env('SAAS_PIX_NOME', 'MedAccess')
SAAS_PIX_CIDADE = env('SAAS_PIX_CIDADE', 'Sao Paulo')

# ---- Produção (HTTPS): ativado automaticamente com DJANGO_DEBUG=0 ----
if not DEBUG:
    SECURE_SSL_REDIRECT = env('SECURE_SSL_REDIRECT', '1') == '1'
    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env('SECURE_HSTS_SECONDS', '0'))
    SECURE_CONTENT_TYPE_NOSNIFF = True
SESSION_COOKIE_AGE = 60 * 60 * 10  # sessão expira após 10h

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'loggers': {'notificacoes': {'handlers': ['console'], 'level': 'INFO'}},
}
