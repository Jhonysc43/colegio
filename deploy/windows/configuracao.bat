@echo off
REM ============================================================
REM  Configuracao do servidor - AJUSTE OS CAMINHOS ABAIXO
REM ============================================================
REM Pasta onde esta o sistema (a que contem app.py)
set APP_DIR=C:\ReceitaCNB\app
REM Banco de dados - FORA da pasta do sistema, para atualizacoes nao tocarem nos dados
set CLOUD_FINANCE_DB=D:\ReceitaCNB\dados\cloud_finance.db
REM Backups automaticos (de preferencia em outro disco ou pasta de rede com copia)
set CLOUD_FINANCE_BACKUP_DIR=D:\ReceitaCNB\backups
set CLOUD_FINANCE_BACKUP_DIAS=30
REM Minutos sem uso ate pedir login de novo
set CLOUD_FINANCE_SESSAO_MIN=30
REM Porta do sistema
set STREAMLIT_SERVER_PORT=8501
REM 0.0.0.0 = acesso direto pela rede (http://servidor:8501).
REM Com o proxy HTTPS do IIS na mesma maquina, use 127.0.0.1 (acesso so pelo IIS).
set STREAMLIT_SERVER_ADDRESS=0.0.0.0
REM Servidor: nao tenta abrir navegador
set STREAMLIT_SERVER_HEADLESS=true
