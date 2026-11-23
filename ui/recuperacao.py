"""Tela de recuperação: aparece no lugar do sistema quando o arquivo de dados está danificado."""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime
from pathlib import Path

import streamlit as st

from core import banco
from core import usuarios as us
from core.marca import NOME_SISTEMA, PREFIXO_ARQUIVOS


def _backups_disponiveis() -> list[tuple[Path, int]]:
    pastas = [banco.pasta_backups_automaticos(), banco.caminho_banco().parent / "backups"]
    vistos, lista = set(), []
    for pasta in pastas:
        if not pasta.exists():
            continue
        for arq in pasta.glob(f"{PREFIXO_ARQUIVOS}_*.db"):
            if arq in vistos or "danificado" in arq.name:
                continue
            vistos.add(arq)
            try:
                n = banco.validar_backup(arq)
            except ValueError:
                continue
            if _tem_usuarios(arq):   # backup de antes da configuração inicial não serve para recuperar
                lista.append((arq, n))
    return sorted(lista, key=lambda x: x[0].stat().st_mtime, reverse=True)[:10]


def _tem_usuarios(arq: Path) -> bool:
    import sqlite3
    con = sqlite3.connect(arq)
    try:
        return con.execute("SELECT COUNT(*) FROM usuarios WHERE perfil = 'administrador' AND ativo = 1").fetchone()[0] > 0
    except sqlite3.DatabaseError:
        return False
    finally:
        con.close()


def _admin_do_backup(backup: Path, login: str, senha: str) -> bool:
    """Confere usuário e senha no próprio backup (numa cópia temporária, sem alterá-lo)."""
    tmp = Path(tempfile.mkdtemp()) / "conferencia.db"
    shutil.copy2(backup, tmp)
    con = banco.conectar(tmp)
    try:
        r = us.autenticar(con, login, senha)
        return r.ok and r.usuario.perfil == "administrador"
    finally:
        con.close()
        shutil.rmtree(tmp.parent, ignore_errors=True)


def pagina(estado: dict):
    st.title(f"💼 {NOME_SISTEMA}")
    st.error("⚠️ **O arquivo de dados apresentou um problema e o sistema foi bloqueado para proteger as "
             "informações.** Nada foi gravado depois da verificação.")
    st.caption(f"Detalhe técnico: {estado['integridade'][:300]}")

    st.subheader("O que fazer")
    st.markdown(
        "1. Peça para **todos fecharem o sistema** nos outros computadores.\n"
        "2. O **administrador** escolhe abaixo o backup mais recente e confirma com o usuário e a senha dele.\n"
        "3. O arquivo danificado é guardado na pasta `backups/antes_de_restaurar`, para análise se necessário.\n"
        "4. Depois de restaurar, **refaça as importações feitas após a data do backup**.")

    backups = _backups_disponiveis()
    if not backups:
        st.warning("Nenhum backup válido foi encontrado nas pastas de backup. Procure a TI: a cópia da pasta "
                   "de dados feita pela rotina de backup da empresa pode ser usada.")
        return
    rotulo = {str(a): f"{datetime.fromtimestamp(a.stat().st_mtime):%d/%m/%Y %H:%M} — {n} transações — {a.name}"
              for a, n in backups}
    escolhido = st.selectbox("Backup a restaurar", list(rotulo), format_func=rotulo.get, key="rec_backup")
    with st.form("rec_form"):
        login = st.text_input("Usuário do administrador")
        senha = st.text_input("Senha", type="password",
                              help="A senha conferida é a que valia na data do backup escolhido.")
        ok = st.checkbox("Entendo que os dados serão substituídos pelos do backup escolhido.")
        if st.form_submit_button("Restaurar backup", type="primary"):
            if not ok:
                st.error("Marque a confirmação.")
            elif not _admin_do_backup(Path(escolhido), login, senha):
                st.error("Usuário ou senha incorretos, ou o usuário não é administrador.")
            else:
                banco.restaurar_backup(escolhido)
                con = banco.conectar()
                try:
                    banco.registrar_auditoria(con, (login or "").strip().lower(), "restauracao_backup",
                                              f"recuperação de arquivo danificado: {Path(escolhido).name}")
                finally:
                    con.close()
                st.cache_resource.clear()
                st.cache_data.clear()
                st.session_state.clear()
                st.success("Backup restaurado. A página será recarregada.")
                st.rerun()
