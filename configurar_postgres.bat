@echo off
title MedAccess - Configurar PostgreSQL
cd /d %~dp0
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
rem Cria o banco do .env (DB_NAME), aplica as migracoes e copia os dados do SQLite.
rem Sem dados para copiar? Use: configurar_postgres.bat --demo
if "%~1"=="" ("%PY%" configurar_postgres.py --copiar) else ("%PY%" configurar_postgres.py %*)
pause
