@echo off
title MedAccess - Django + PostgreSQL (atras do Caddy/HTTPS)
REM Copie o projeto para C:\webapps\clinica no servidor e crie o venv:
REM   python -m venv venv  &&  venv\Scripts\pip install -r requirements.txt
REM Use o .env.producao.example como base do .env do servidor.

cd /d C:\webapps\clinica

if not exist "venv\Scripts\python.exe" (
    echo ERRO: Ambiente virtual nao encontrado em C:\webapps\clinica\venv
    pause
    exit /b 1
)

echo Verificando o PostgreSQL...
"venv\Scripts\python.exe" manage.py verificar_banco
if errorlevel 1 (
    echo ERRO: sem conexao com o PostgreSQL. Confira o .env do servidor.
    pause
    exit /b 1
)
"venv\Scripts\python.exe" manage.py migrate --noinput
"venv\Scripts\python.exe" manage.py collectstatic --noinput >nul

echo Iniciando MedAccess...
echo Acesso publico pelo Caddy: https://clinica.arpjr.com.br  ou  https://24.152.36.103:8003/
echo.
REM Porta interna: so o Caddy (mesma maquina) acessa. --insecure serve os arquivos estaticos com DEBUG=0.
"venv\Scripts\python.exe" manage.py runserver 127.0.0.1:18003 --insecure --noreload

pause
