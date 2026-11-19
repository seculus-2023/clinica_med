@echo off
title MedAccess - Configurar banco PostgreSQL
cd /d %~dp0
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
rem Cria no PostgreSQL o banco definido no .env (DB_NAME) e aplica as tabelas.
rem Uso direto: configurar_postgres.bat [--copiar ^| --demo]
if not "%~1"=="" (
    "%PY%" configurar_postgres.py %*
    goto :fim
)
echo ================================================
echo   CONFIGURAR BANCO POSTGRESQL
echo ================================================
echo   1 - Criar o banco vazio (producao)
echo   2 - Criar o banco com dados de demonstracao
echo   3 - Criar o banco e copiar os dados do db.sqlite3 antigo
echo ================================================
choice /c 123 /n /m "Escolha 1, 2 ou 3: "
if errorlevel 3 (
    "%PY%" configurar_postgres.py --copiar
) else if errorlevel 2 (
    "%PY%" configurar_postgres.py --demo
) else (
    "%PY%" configurar_postgres.py
    echo.
    echo Crie o primeiro administrador:
    "%PY%" manage.py createsuperuser
)
:fim
echo.
"%PY%" manage.py verificar_banco
pause
