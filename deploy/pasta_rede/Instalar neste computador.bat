@echo off
setlocal
title Preparar este computador - Receita Colegio Notarial do Brasil
REM ============================================================
REM  Executar UMA VEZ em cada computador que vai usar o sistema
REM  (e de novo quando uma atualizacao pedir). Nao precisa ser administrador.
REM  Instala as bibliotecas em %LOCALAPPDATA%\ReceitaCNB e cria o atalho na Area de Trabalho.
REM ============================================================
set "RAIZ=%~dp0"
set "VENV=%LOCALAPPDATA%\ReceitaCNB\venv"

REM 1. Python 3.11 ou mais recente
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo  Python 3.11 ou mais recente nao foi encontrado neste computador.
    echo  Instale pelo site python.org ^(marque "Add Python to PATH"^) ou peca a TI,
    echo  e execute este arquivo de novo.
    echo.
    pause
    exit /b 1
)

REM 2. Ambiente proprio do sistema, neste computador
if not exist "%VENV%\Scripts\python.exe" (
    echo Criando o ambiente do sistema...
    %PY% -m venv "%VENV%" || goto erro
)

REM 3. Bibliotecas (da pasta "pacotes", se existir; senao, da internet)
echo Instalando as bibliotecas (pode levar alguns minutos)...
if exist "%RAIZ%pacotes\" (
    "%VENV%\Scripts\python.exe" -m pip install --no-index --find-links "%RAIZ%pacotes" -r "%RAIZ%app\requirements.txt" || goto erro
) else (
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >nul
    "%VENV%\Scripts\python.exe" -m pip install -r "%RAIZ%app\requirements.txt" || goto erro
)

REM 4. Evita a pergunta de e-mail do Streamlit na primeira execucao
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    > "%USERPROFILE%\.streamlit\credentials.toml" echo [general]
    >> "%USERPROFILE%\.streamlit\credentials.toml" echo email = ""
)

REM 5. Atalho na Area de Trabalho
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Receita CNB.lnk'); $s.TargetPath='%RAIZ%Abrir Receita CNB.bat'; $s.WorkingDirectory='%RAIZ%'; $s.IconLocation='%SystemRoot%\System32\shell32.dll,43'; $s.Save()"

echo.
echo  Pronto! Use o atalho "Receita CNB" na Area de Trabalho para abrir o sistema.
echo.
pause
exit /b 0

:erro
echo.
echo  Algo deu errado na instalacao. Tire um print desta janela e envie para quem cuida do sistema.
echo.
pause
exit /b 1
