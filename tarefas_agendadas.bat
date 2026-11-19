@echo off
rem Execucao manual das rotinas (as tarefas do Agendador do Windows ja rodam sozinhas, sem janela).
cd /d %~dp0
set "PY=python"
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
"%PY%" executar_tarefa.py processar_lembretes
if "%~1"=="backup" "%PY%" executar_tarefa.py backup --manter 30
type logs\tarefas.log | more
