@echo off
setlocal
title Receita Colegio Notarial do Brasil
REM ============================================================
REM  Abre o sistema neste computador, com os dados na pasta de rede.
REM  Fica na raiz da pasta do sistema (ex.: Z:\ReceitaCNB).
REM ============================================================
set "RAIZ=%~dp0"
set "VENV=%LOCALAPPDATA%\ReceitaCNB\venv"
set "PORTA=8501"

if not exist "%VENV%\Scripts\python.exe" (
    echo.
    echo  Este computador ainda nao foi preparado para o sistema.
    echo  Execute uma vez o arquivo "Instalar neste computador.bat", na mesma pasta.
    echo.
    pause
    exit /b 1
)

REM Se o sistema ja estiver aberto neste computador, so abre o navegador
curl -s -m 2 http://localhost:%PORTA%/_stcore/health 2>nul | find "ok" >nul
if %ERRORLEVEL%==0 (
    start "" http://localhost:%PORTA%
    exit /b 0
)

set "CLOUD_FINANCE_DB=%RAIZ%dados\cloud_finance.db"
set "CLOUD_FINANCE_MODO=rede"
set "CLOUD_FINANCE_SESSAO_MIN=30"
REM So este computador acessa o sistema que roda nele
set "STREAMLIT_SERVER_ADDRESS=127.0.0.1"
set "STREAMLIT_SERVER_PORT=%PORTA%"
set "STREAMLIT_BROWSER_SERVER_ADDRESS=localhost"
set "STREAMLIT_SERVER_HEADLESS=false"
REM Nao grava arquivos de cache do Python na pasta de rede
set "PYTHONDONTWRITEBYTECODE=1"

pushd "%RAIZ%app"
echo.
echo  Abrindo o sistema no navegador...
echo  MANTENHA ESTA JANELA ABERTA enquanto usar o sistema.
echo  Para fechar: feche o navegador e depois esta janela.
echo.
"%VENV%\Scripts\python.exe" -m streamlit run app.py
popd
