@echo off
setlocal
title Montar ou atualizar a pasta do sistema na rede
REM ============================================================
REM  Executar no computador da administradora, a partir da pasta do sistema
REM  (a que foi descompactada, com app.py). Monta ou ATUALIZA a pasta na rede.
REM  - Copia o programa para <destino>\app (substitui a versao anterior)
REM  - Coloca os atalhos "Abrir" e "Instalar" na raiz do destino
REM  - Na primeira vez, leva os dados atuais deste computador para <destino>\dados
REM  Os dados que ja estiverem na rede NUNCA sao substituidos por este arquivo.
REM ============================================================
set "ORIGEM=%~dp0..\.."
for %%I in ("%ORIGEM%") do set "ORIGEM=%%~fI"
set "DESTINO=Z:\ReceitaCNB"
set /p "DESTINO=Pasta do sistema na rede [%DESTINO%]: "

if not exist "%ORIGEM%\app.py" (
    echo Nao encontrei app.py em %ORIGEM%. Execute este arquivo de dentro da pasta deploy\pasta_rede.
    pause
    exit /b 1
)

echo.
echo  ATENCAO: todos devem FECHAR o sistema antes de continuar (atualizacao do programa).
pause

if not exist "%DESTINO%\dados" mkdir "%DESTINO%\dados"

echo Copiando o programa...
robocopy "%ORIGEM%" "%DESTINO%\app" /MIR /XD .venv dados logs __pycache__ .git /XF *.pyc /NFL /NDL /NJH /NJS /NP
if %ERRORLEVEL% GEQ 8 goto erro
copy /Y "%ORIGEM%\deploy\pasta_rede\Abrir Receita CNB.bat" "%DESTINO%\" >nul || goto erro
copy /Y "%ORIGEM%\deploy\pasta_rede\Instalar neste computador.bat" "%DESTINO%\" >nul || goto erro

if exist "%DESTINO%\dados\cloud_finance.db" (
    echo Os dados ja estao na rede: foram mantidos como estao.
) else (
    echo Levando os dados deste computador para a rede...
    call :levar || goto erro
)

echo.
echo  Pronto. Pasta do sistema: %DESTINO%
echo  Em cada computador, execute uma vez "%DESTINO%\Instalar neste computador.bat".
echo.
pause
exit /b 0

:levar
if exist "%ORIGEM%\.venv\Scripts\python.exe" (
    "%ORIGEM%\.venv\Scripts\python.exe" "%ORIGEM%\scripts\levar_dados.py" "%ORIGEM%\dados\cloud_finance.db" "%DESTINO%\dados\cloud_finance.db"
) else (
    py -3 "%ORIGEM%\scripts\levar_dados.py" "%ORIGEM%\dados\cloud_finance.db" "%DESTINO%\dados\cloud_finance.db"
)
exit /b %ERRORLEVEL%

:erro
echo.
echo  Algo deu errado. Tire um print desta janela e envie para quem cuida do sistema.
pause
exit /b 1
