@echo off
REM ============================================================
REM  Instala o sistema como servico do Windows (inicia sozinho com o servidor).
REM  Requer o NSSM (https://nssm.cc) no PATH. Execute como Administrador.
REM ============================================================
call "%~dp0configuracao.bat"
set SERVICO=ReceitaCNB
if not exist "%CLOUD_FINANCE_BACKUP_DIR%" mkdir "%CLOUD_FINANCE_BACKUP_DIR%"
for %%I in ("%CLOUD_FINANCE_DB%") do if not exist "%%~dpI" mkdir "%%~dpI"
if not exist "%APP_DIR%\logs" mkdir "%APP_DIR%\logs"

nssm install %SERVICO% "%APP_DIR%\.venv\Scripts\python.exe" "-m streamlit run app.py"
nssm set %SERVICO% AppEnvironmentExtra "CLOUD_FINANCE_DB=%CLOUD_FINANCE_DB%" "CLOUD_FINANCE_SESSAO_MIN=%CLOUD_FINANCE_SESSAO_MIN%" "STREAMLIT_SERVER_PORT=%STREAMLIT_SERVER_PORT%" "STREAMLIT_SERVER_ADDRESS=%STREAMLIT_SERVER_ADDRESS%" "STREAMLIT_SERVER_HEADLESS=true"
nssm set %SERVICO% DisplayName "Receita Colegio Notarial do Brasil"
nssm set %SERVICO% Description "Sistema de gestao e conciliacao de receitas (Streamlit)"
nssm set %SERVICO% AppDirectory "%APP_DIR%"
nssm set %SERVICO% Start SERVICE_AUTO_START
nssm set %SERVICO% AppStdout "%APP_DIR%\logs\servico.log"
nssm set %SERVICO% AppStderr "%APP_DIR%\logs\servico.log"
nssm set %SERVICO% AppRotateFiles 1
nssm set %SERVICO% AppRotateBytes 10485760
nssm start %SERVICO%

REM Se mudar algo em configuracao.bat depois, rode este arquivo de novo
REM (ou: nssm edit %SERVICO%) e reinicie o servico: nssm restart %SERVICO%

REM Backup diario as 22h
schtasks /Create /TN "ReceitaCNB - Backup diario" /TR "\"%~dp0backup_diario.bat\"" /SC DAILY /ST 22:00 /RU SYSTEM /F

echo.
echo Pronto. Teste em http://localhost:%STREAMLIT_SERVER_PORT%
echo Saude do sistema: http://localhost:%STREAMLIT_SERVER_PORT%/_stcore/health  (deve responder "ok")
pause
