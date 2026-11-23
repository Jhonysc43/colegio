@echo off
REM Executado pelo Agendador de Tarefas todos os dias.
call "%~dp0configuracao.bat"
cd /d "%APP_DIR%"
"%APP_DIR%\.venv\Scripts\python.exe" scripts\backup_automatico.py >> "%CLOUD_FINANCE_BACKUP_DIR%\backup.log" 2>&1
exit /b %ERRORLEVEL%
