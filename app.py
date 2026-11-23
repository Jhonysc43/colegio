"""Receita Colégio Notarial do Brasil — ponto de entrada.

Executar:  streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

from core.marca import NOME_SISTEMA  # noqa: E402

st.set_page_config(page_title=NOME_SISTEMA, page_icon="💼", layout="wide")

from core import banco, classificacao  # noqa: E402
from ui import (boletos, conciliacao, configuracoes, dashboard, importacoes, receita_diaria,  # noqa: E402
                recuperacao, relatorios, transacoes)
from core.usuarios import pode_ver  # noqa: E402
from ui.auth import barra_usuario, exigir_login, perfil_atual  # noqa: E402
from ui.comum import aplicar_estilo  # noqa: E402


@st.cache_resource
def preparar_banco() -> dict:
    """Uma vez por processo (no modo pasta de rede: cada vez que alguém abre o programa).

    Confere se o arquivo do banco está íntegro ANTES de gravar qualquer coisa; se estiver,
    cria/atualiza o esquema, aplica atualizações de regras e faz o backup do dia, se ainda
    não houver um. Se o arquivo tiver problema, as gravações ficam bloqueadas.
    """
    estado = {"integridade": "ok", "backup": None, "erro_backup": None}
    con = banco.conectar()
    try:
        existia = con.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0] > 0
        if existia:
            estado["integridade"] = banco.verificar_integridade(con)
        if estado["integridade"] != "ok":
            return estado
        banco.inicializar(con)
        classificacao.semear_regras(con)
    finally:
        con.close()
    try:
        estado["backup"] = banco.backup_diario_se_preciso()
    except Exception as e:  # noqa: BLE001 — o backup nunca impede o uso do sistema
        estado["erro_backup"] = str(e)
    return estado


def conexao():
    """Uma conexão por sessão de usuário: sessões simultâneas não dividem transações."""
    estado = preparar_banco()
    if "_con" not in st.session_state:
        con = banco.conectar()
        if estado["integridade"] != "ok":
            con.bloquear_gravacao = "o arquivo de dados apresentou problema na verificação"
        st.session_state["_con"] = con
    return st.session_state["_con"]


def aviso_backup():
    estado = preparar_banco()
    if estado["erro_backup"] and perfil_atual() == "administrador":
        st.warning(f"O backup automático de hoje não pôde ser feito: {estado['erro_backup'][:300]}. "
                   "Gere um backup manual em Configurações → Backup.")


PAGINAS = {
    "Dashboard": ("📊", dashboard.pagina),
    "Receita Diária": ("📅", receita_diaria.pagina),
    "Boletos Processados": ("🧾", boletos.pagina),
    "Transações": ("📋", transacoes.pagina),
    "Conciliação": ("✅", conciliacao.pagina),
    "Relatórios": ("📑", relatorios.pagina),
    "Importações": ("📥", importacoes.pagina),
    "Configurações": ("⚙️", configuracoes.pagina),
}


def main():
    aplicar_estilo()
    estado = preparar_banco()
    if estado["integridade"] != "ok":   # arquivo danificado: só a tela de recuperação
        recuperacao.pagina(estado)
        st.stop()
    con = conexao()
    usuario = exigir_login(con)  # interrompe aqui se não houver login válido
    permitidas = [n for n in PAGINAS if pode_ver(usuario.perfil, n)]
    if st.session_state.get("pagina") not in permitidas:
        st.session_state.pop("pagina", None)
    with st.sidebar:
        st.markdown(f"### 💼 {NOME_SISTEMA}")
        nome = st.radio("Navegação", permitidas, format_func=lambda n: f"{PAGINAS[n][0]}  {n}",
                        key="pagina", label_visibility="collapsed")
        st.divider()
    barra_usuario(con, usuario)
    aviso_backup()
    PAGINAS[nome][1](con)


main()
