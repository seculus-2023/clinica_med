@echo off
rem Execucao manual das rotinas (as tarefas do Agendador do Windows ja rodam sozinhas, sem janela).
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
"%PY%" executar_tarefa.py processar_lembretes
if "%~1"=="backup" "%PY%" executar_tarefa.py backup --manter 30
type logs\tarefas.log | more
