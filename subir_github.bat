@echo off
title Clinica Med - Enviar para o GitHub
cd /d C:\PROJETOS_PYTHON\Clinica

set REPO_URL=https://github.com/seculus-2023/clinica_med.git

echo ========================================
echo   CLINICA MED - ENVIAR PARA O GITHUB
echo ========================================
echo.

rem --- Primeira execucao: cria o repositorio local e liga ao GitHub ---
if not exist ".git" (
    echo Repositorio local nao encontrado. Inicializando...
    git init
    git branch -M main
)
git remote get-url origin >nul 2>&1
if errorlevel 1 (
    echo Configurando remoto: %REPO_URL%
    git remote add origin %REPO_URL%
)

git status --short
echo.

for /f "tokens=1-4 delims=/ " %%a in ('date /t') do set DATA_HOJE=%%a_%%b_%%c
for /f "tokens=1-2 delims=: " %%a in ('time /t') do set HORA_AGORA=%%a%%b
set MENSAGEM=%DATA_HOJE%_%HORA_AGORA%
echo Mensagem do commit (automatica): %MENSAGEM%
echo.

rem O .gitignore impede o envio do .env, banco de dados e arquivos de midia
git add .
git commit -m "%MENSAGEM%"
if errorlevel 1 (
    echo.
    echo Nenhuma alteracao nova para commitar - enviando os commits que ja existem.
)

echo.
echo Enviando para o GitHub...
git push -u origin main
if errorlevel 1 (
    echo.
    echo ERRO: falha ao enviar para o GitHub. Verifique sua conexao/login e tente de novo.
    echo Se o repositorio remoto ja tiver arquivos, rode antes: git pull origin main --allow-unrelated-histories
    pause
    exit /b 1
)

echo.
echo Codigo enviado com sucesso!
pause
