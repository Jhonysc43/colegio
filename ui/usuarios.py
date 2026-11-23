"""Cadastro de usuários (somente administrador)."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core import usuarios as us

from .auth import pode


def _mostrar_senha_temporaria():
    info = st.session_state.pop("senha_temp", None)
    if info:
        login, senha = info
        st.success(f"Senha temporária de **{login}**: `{senha}`  \n"
                   "Anote e entregue à pessoa de forma reservada. Ela não será exibida de novo. "
                   "No primeiro acesso, o sistema pedirá que a pessoa crie a própria senha.")


def secao(con, usuario: str):
    if not pode("gerenciar_usuarios"):
        st.error("Somente o administrador gerencia usuários.")
        return
    _mostrar_senha_temporaria()
    if st.session_state.get("usr_msg"):
        st.success(st.session_state.pop("usr_msg"))

    lista = us.listar(con)
    st.dataframe(pd.DataFrame([{
        "Nome": u.nome, "Usuário": u.login, "Perfil": u.perfil_nome, "E-mail": u.email or "",
        "Situação": "Ativo" if u.ativo else "Desativado",
        "Último acesso": pd.to_datetime(u.ultimo_acesso).strftime("%d/%m/%Y %H:%M") if u.ultimo_acesso else "—",
        "Senha": "Temporária" if u.trocar_senha else "Definida"} for u in lista]), hide_index=True)
    st.caption("Perfis — **Administrador**: tudo. **Operador**: importa, classifica, resolve conflitos e exporta. "
               "**Consulta**: acompanha todas as telas e exporta, sem alterar dados.")

    st.markdown("**Novo usuário**")
    with st.form("usr_novo", clear_on_submit=True):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome completo")
        login = c2.text_input("Usuário", help="Ex.: joana.souza — letras sem acento, números, ponto ou hífen.")
        c3, c4 = st.columns(2)
        email = c3.text_input("E-mail (opcional)")
        perfil = c4.selectbox("Perfil", list(us.PERFIS), format_func=us.PERFIS.get, index=1)
        if st.form_submit_button("Cadastrar", type="primary"):
            temp = us.gerar_senha_temporaria()
            try:
                u = us.criar(con, login, nome, perfil, temp, usuario, email=email)
            except us.ErroUsuario as e:
                st.error(str(e))
            else:
                st.session_state["senha_temp"] = (u.login, temp)
                st.rerun()

    st.markdown("**Alterar usuário**")
    logins = [u.login for u in lista]
    escolhido = st.selectbox("Usuário", logins, index=None, placeholder="Escolha...", key="usr_sel",
                             format_func=lambda l: next(f"{u.nome} ({u.login})" for u in lista if u.login == l))
    if not escolhido:
        return
    u = us.buscar(con, escolhido)
    with st.form(f"usr_edit_{u.login}"):
        c1, c2 = st.columns(2)
        nome = c1.text_input("Nome completo", value=u.nome)
        email = c2.text_input("E-mail", value=u.email or "")
        c3, c4 = st.columns(2)
        perfil = c3.selectbox("Perfil", list(us.PERFIS), format_func=us.PERFIS.get,
                              index=list(us.PERFIS).index(u.perfil))
        ativo = c4.checkbox("Ativo", value=u.ativo, help="Usuários não são apagados, apenas desativados, "
                                                         "para manter o histórico da auditoria.")
        if st.form_submit_button("Salvar alterações", type="primary"):
            try:
                us.alterar(con, u.login, usuario, nome=nome, email=email.strip(), perfil=perfil, ativo=ativo)
            except us.ErroUsuario as e:
                st.error(str(e))
            else:
                st.session_state["usr_msg"] = f"Usuário {u.login} atualizado."
                st.rerun()
    if st.button("Redefinir senha", key=f"usr_reset_{u.login}",
                 help="Gera uma senha temporária. A pessoa cria uma nova no próximo acesso."):
        st.session_state["senha_temp"] = (u.login, us.redefinir_senha(con, u.login, usuario))
        st.rerun()
