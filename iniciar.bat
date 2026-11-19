@echo off
title MedAccess - Servidor (PostgreSQL)
cd /d %~dp0
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
echo Verificando o PostgreSQL...
"%PY%" manage.py verificar_banco
if errorlevel 1 (
    echo.
    echo Nao foi possivel conectar ao PostgreSQL. Corrija o .env ^(DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT^)
    echo ou rode configurar_postgres.bat para criar o banco.
    pause
    exit /b 1
)
"%PY%" manage.py migrate --noinput
if errorlevel 1 (
    echo ERRO ao atualizar o banco PostgreSQL.
    pause
    exit /b 1
)
echo.
echo Acesse: http://localhost:8000   (Ctrl+C para parar)
"%PY%" manage.py runserver 0.0.0.0:8000
