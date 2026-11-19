@echo off
title MedAccess - Servidor
cd /d %~dp0
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" manage.py migrate --noinput
echo.
echo Acesse: http://localhost:8000   (Ctrl+C para parar)
"%PY%" manage.py runserver 0.0.0.0:8000
