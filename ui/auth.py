"""Login, sessão e permissões na interface."""
from __future__ import annotations

from datetime import datetime

import streamlit as st

from core import usuarios as us
from core.banco import registrar_auditoria
from core.marca import NOME_SISTEMA, SUBTITULO

CHAVES_SESSAO = ("usuario", "perfil", "nome", "ultima_atividade")


def _encerrar(motivo: str | None = None):
    for k in CHAVES_SESSAO:
        st.session_state.pop(k, None)
    if motivo:
        st.session_state["aviso_login"] = motivo


def usuario_atual() -> str | None:
    return st.session_state.get("usuario")


def perfil_atual() -> str | None:
    return st.session_state.get("perfil")


def pode(acao: str) -> bool:
    return us.pode(perfil_atual(), acao)


def _centro():
    _, meio, _ = st.columns([1, 1.4, 1])
    return meio


def _primeiro_acesso(con):
    with _centro():
        st.title(f"💼 {NOME_SISTEMA}")
        st.subheader("Primeiro acesso")
        st.write("Nenhum usuário cadastrado ainda. Crie o usuário **administrador**. "
                 "Depois, ele cadastra os demais usuários em Configurações → Usuários.")
        with st.form("primeiro_acesso"):
            nome = st.text_input("Nome completo")
            login = st.text_input("Usuário", help="Ex.: maria.silva — letras sem acento, números, ponto ou hífen.")
            email = st.text_input("E-mail (opcional)")
            senha = st.text_input("Senha", type="password",
                                  help=f"Pelo menos {us.SENHA_MIN} caracteres, com letras e números.")
            senha2 = st.text_input("Repita a senha", type="password")
            if st.form_submit_button("Criar administrador", type="primary"):
                if senha != senha2:
                    st.error("As senhas não conferem.")
                else:
                    try:
                        u = us.criar_primeiro_administrador(con, login, nome, senha, email)
                    except us.ErroUsuario as e:
                        st.error(str(e))
                    else:
                        st.session_state["aviso_login"] = f"Administrador '{u.login}' criado. Entre com a sua senha."
                        st.rerun()


def _tela_login(con):
    with _centro():
        st.title(f"💼 {NOME_SISTEMA}")
        st.caption(SUBTITULO)
        if st.session_state.get("aviso_login"):
            st.info(st.session_state.pop("aviso_login"))
        with st.form("login"):
            login = st.text_input("Usuário")
            senha = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", type="primary", width="stretch"):
                r = us.autenticar(con, login, senha)
                if r.ok:
                    st.session_state.update(usuario=r.usuario.login, perfil=r.usuario.perfil, nome=r.usuario.nome,
                                            ultima_atividade=datetime.now().isoformat())
                    st.rerun()
                else:
                    st.error(r.mensagem)
        st.caption("Esqueceu a senha? Peça ao administrador para redefini-la.")


def _form_troca_senha(con, login: str, chave: str) -> bool:
    with st.form(chave, clear_on_submit=True):
        atual = st.text_input("Senha atual", type="password")
        nova = st.text_input("Nova senha", type="password",
                             help=f"Pelo menos {us.SENHA_MIN} caracteres, com letras e números.")
        nova2 = st.text_input("Repita a nova senha", type="password")
        if st.form_submit_button("Trocar senha", type="primary"):
            if nova != nova2:
                st.error("As senhas novas não conferem.")
                return False
            try:
                us.trocar_senha(con, login, atual, nova)
            except us.ErroUsuario as e:
                st.error(str(e))
                return False
            return True
    return False


def _troca_obrigatoria(con, login: str):
    with _centro():
        st.title(f"💼 {NOME_SISTEMA}")
        st.subheader("Crie a sua senha")
        st.write("Você entrou com uma senha temporária. Para continuar, defina uma senha pessoal.")
        if _form_troca_senha(con, login, "troca_obrigatoria"):
            st.success("Senha alterada.")
            st.rerun()
        if st.button("Sair"):
            _encerrar()
            st.rerun()


def exigir_login(con) -> us.Usuario:
    """Garante um usuário autenticado e ativo; caso contrário mostra a tela adequada e interrompe."""
    if not us.existe_usuario(con):
        _primeiro_acesso(con)
        st.stop()

    login = usuario_atual()
    if login:
        ultima = st.session_state.get("ultima_atividade")
        limite = us.minutos_sessao()
        if ultima and (datetime.now() - datetime.fromisoformat(ultima)).total_seconds() > limite * 60:
            registrar_auditoria(con, login, "sessao_expirada", "")
            _encerrar(f"Sua sessão expirou após {limite} minutos sem uso. Entre novamente.")
            login = None
    u = us.buscar(con, login) if login else None
    if login and (u is None or not u.ativo):
        _encerrar("Seu acesso foi desativado. Fale com o administrador.")
        u = None
    if u is None:
        _tela_login(con)
        st.stop()
    # perfil pode ter sido alterado pelo administrador durante a sessão
    st.session_state.update(perfil=u.perfil, nome=u.nome, ultima_atividade=datetime.now().isoformat())
    if u.trocar_senha:
        _troca_obrigatoria(con, u.login)
        st.stop()
    return u


def barra_usuario(con, u: us.Usuario):
    with st.sidebar:
        st.markdown(f"👤 **{u.nome}**  \n{u.perfil_nome}")
        with st.expander("Minha senha"):
            if _form_troca_senha(con, u.login, "troca_voluntaria"):
                st.success("Senha alterada.")
        if st.button("Sair", width="stretch", key="btn_sair"):
            registrar_auditoria(con, u.login, "logout", "")
            _encerrar("Você saiu do sistema.")
            st.rerun()
        st.divider()
