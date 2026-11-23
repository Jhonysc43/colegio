@echo off
REM Inicia o sistema manualmente (para teste antes de instalar o servico).
call "%~dp0configuracao.bat"
cd /d "%APP_DIR%"
"%APP_DIR%\.venv\Scripts\python.exe" -m streamlit run app.py
