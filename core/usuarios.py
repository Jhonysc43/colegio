"""Usuários, senhas e permissões.

Segurança:
- Senhas nunca são guardadas: guarda-se apenas o resultado do scrypt (função de
  derivação lenta, resistente a força bruta) com um "sal" aleatório por usuário.
- Comparação em tempo constante (hmac.compare_digest).
- Bloqueio temporário após várias tentativas erradas.
- Não existe usuário ou senha padrão no código: o primeiro administrador é
  criado na tela de primeiro acesso.
- Usuários não são apagados, só desativados (preserva a auditoria).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from .banco import agora, registrar_auditoria, transacao

PERFIS = {
    "administrador": "Administrador",
    "operador": "Operador",
    "consulta": "Consulta",
}

# Telas que cada perfil pode abrir
TELAS = {
    "administrador": {"Dashboard", "Receita Diária", "Boletos Processados", "Transações", "Conciliação",
                      "Relatórios", "Importações", "Configurações"},
    "operador": {"Dashboard", "Receita Diária", "Boletos Processados", "Transações", "Conciliação",
                 "Relatórios", "Importações", "Configurações"},
    "consulta": {"Dashboard", "Receita Diária", "Boletos Processados", "Transações", "Conciliação", "Relatórios"},
}

# Ações que alteram dados
ACOES = {
    "importar": {"administrador", "operador"},
    "excluir_importacao": {"administrador"},
    "resolver_conflito": {"administrador", "operador"},
    "classificar_manual": {"administrador", "operador"},
    "editar_regras": {"administrador"},
    "editar_receitas": {"administrador"},
    "regra_inclusao": {"administrador"},
    "backup": {"administrador"},
    "ver_auditoria": {"administrador"},
    "gerenciar_usuarios": {"administrador"},
    "exportar": {"administrador", "operador", "consulta"},
}

MAX_TENTATIVAS = 5
MINUTOS_BLOQUEIO = 15
SENHA_MIN = 8
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1}


class ErroUsuario(ValueError):
    pass


def pode(perfil: str | None, acao: str) -> bool:
    return perfil in ACOES.get(acao, set())


def pode_ver(perfil: str | None, tela: str) -> bool:
    return tela in TELAS.get(perfil or "", set())


# ------------------------------------------------------------------------ senhas
def gerar_hash(senha: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(senha.encode(), salt=sal, dklen=64, **_SCRYPT)
    return "scrypt${n}${r}${p}${sal}${h}".format(**_SCRYPT, sal=base64.b64encode(sal).decode(),
                                                    h=base64.b64encode(h).decode())


def conferir_senha(senha: str, guardado: str) -> bool:
    try:
        alg, n, r, p, sal, h = guardado.split("$")
        if alg != "scrypt":
            return False
        calc = hashlib.scrypt(senha.encode(), salt=base64.b64decode(sal), dklen=64, n=int(n), r=int(r), p=int(p))
        return hmac.compare_digest(calc, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def validar_senha(senha: str, login: str = "") -> list[str]:
    erros = []
    if len(senha) < SENHA_MIN:
        erros.append(f"A senha deve ter pelo menos {SENHA_MIN} caracteres.")
    if not re.search(r"[A-Za-zÀ-ÿ]", senha) or not re.search(r"\d", senha):
        erros.append("A senha deve ter letras e números.")
    if login and login.lower() in senha.lower():
        erros.append("A senha não pode conter o nome de usuário.")
    return erros


def gerar_senha_temporaria() -> str:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    while True:
        s = "".join(secrets.choice(alfabeto) for _ in range(10))
        if not validar_senha(s):
            return s


# ---------------------------------------------------------------------- usuários
@dataclass
class Usuario:
    id: int
    login: str
    nome: str
    email: str | None
    perfil: str
    ativo: bool
    trocar_senha: bool
    ultimo_acesso: str | None

    @property
    def perfil_nome(self) -> str:
        return PERFIS.get(self.perfil, self.perfil)


def _usuario(r) -> Usuario:
    return Usuario(r["id"], r["login"], r["nome"], r["email"], r["perfil"], bool(r["ativo"]),
                   bool(r["trocar_senha"]), r["ultimo_acesso"])


def _normalizar_login(login: str) -> str:
    login = (login or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,40}", login):
        raise ErroUsuario("Usuário deve ter de 3 a 40 caracteres: letras sem acento, números, ponto, hífen ou _.")
    return login


def existe_usuario(con) -> bool:
    return con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0


def listar(con) -> list[Usuario]:
    return [_usuario(r) for r in con.execute("SELECT * FROM usuarios ORDER BY ativo DESC, perfil, nome")]


def buscar(con, login: str) -> Usuario | None:
    r = con.execute("SELECT * FROM usuarios WHERE login = ?", ((login or "").strip().lower(),)).fetchone()
    return _usuario(r) if r else None


def criar(con, login: str, nome: str, perfil: str, senha: str, por: str | None, email: str = "",
          trocar_senha: bool = True) -> Usuario:
    login = _normalizar_login(login)
    if perfil not in PERFIS:
        raise ErroUsuario("Perfil inválido.")
    if not (nome or "").strip():
        raise ErroUsuario("Informe o nome.")
    erros = validar_senha(senha, login)
    if erros:
        raise ErroUsuario(" ".join(erros))
    if buscar(con, login):
        raise ErroUsuario(f"Já existe o usuário '{login}'.")
    with transacao(con):
        con.execute(
            "INSERT INTO usuarios (login, nome, email, perfil, senha_hash, ativo, trocar_senha, criado_em,"
            " tentativas_falhas) VALUES (?,?,?,?,?,1,?,?,0)",
            (login, nome.strip(), (email or "").strip() or None, perfil, gerar_hash(senha),
             1 if trocar_senha else 0, agora()))
        registrar_auditoria(con, por, "usuario_criado", json.dumps(
            {"login": login, "nome": nome.strip(), "perfil": perfil}, ensure_ascii=False))
    return buscar(con, login)


def criar_primeiro_administrador(con, login: str, nome: str, senha: str, email: str = "") -> Usuario:
    if existe_usuario(con):
        raise ErroUsuario("O primeiro administrador já foi criado.")
    return criar(con, login, nome, "administrador", senha, por=(login or "").strip().lower(), email=email,
                 trocar_senha=False)


@dataclass
class ResultadoLogin:
    ok: bool
    usuario: Usuario | None = None
    mensagem: str = ""


def autenticar(con, login: str, senha: str) -> ResultadoLogin:
    login = (login or "").strip().lower()
    erro = ResultadoLogin(False, mensagem="Usuário ou senha incorretos.")  # não revela se o usuário existe
    r = con.execute("SELECT * FROM usuarios WHERE login = ?", (login,)).fetchone()
    if not r:
        hashlib.scrypt(b"x", salt=b"0" * 16, dklen=64, **_SCRYPT)  # mesmo tempo de resposta
        registrar_auditoria(con, login or None, "login_falhou", "usuário inexistente")
        return erro
    if not r["ativo"]:
        registrar_auditoria(con, login, "login_falhou", "usuário desativado")
        return ResultadoLogin(False, mensagem="Usuário desativado. Fale com o administrador.")
    if r["bloqueado_ate"] and r["bloqueado_ate"] > agora():
        fim = datetime.fromisoformat(r["bloqueado_ate"])
        return ResultadoLogin(False, mensagem=f"Acesso bloqueado por tentativas erradas até {fim:%H:%M}.")
    if not conferir_senha(senha or "", r["senha_hash"]):
        falhas = (r["tentativas_falhas"] or 0) + 1
        bloqueio = None
        if falhas >= MAX_TENTATIVAS:
            bloqueio = (datetime.now() + timedelta(minutes=MINUTOS_BLOQUEIO)).isoformat(timespec="seconds")
            falhas = 0
        con.execute("UPDATE usuarios SET tentativas_falhas = ?, bloqueado_ate = ? WHERE id = ?",
                    (falhas, bloqueio, r["id"]))
        registrar_auditoria(con, login, "login_falhou", "senha incorreta" + (" — bloqueado" if bloqueio else ""))
        if bloqueio:
            return ResultadoLogin(False, mensagem=f"Muitas tentativas erradas. Acesso bloqueado por "
                                                  f"{MINUTOS_BLOQUEIO} minutos.")
        return erro
    con.execute("UPDATE usuarios SET tentativas_falhas = 0, bloqueado_ate = NULL, ultimo_acesso = ? WHERE id = ?",
                (agora(), r["id"]))
    registrar_auditoria(con, login, "login", "")
    return ResultadoLogin(True, buscar(con, login))


def trocar_senha(con, login: str, senha_atual: str, nova: str) -> None:
    r = con.execute("SELECT * FROM usuarios WHERE login = ?", (login,)).fetchone()
    if not r or not conferir_senha(senha_atual, r["senha_hash"]):
        raise ErroUsuario("Senha atual incorreta.")
    erros = validar_senha(nova, login)
    if conferir_senha(nova, r["senha_hash"]):
        erros.append("A nova senha deve ser diferente da atual.")
    if erros:
        raise ErroUsuario(" ".join(erros))
    con.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 0 WHERE id = ?", (gerar_hash(nova), r["id"]))
    registrar_auditoria(con, login, "senha_alterada", "")


def _administradores_ativos(con) -> int:
    return con.execute("SELECT COUNT(*) FROM usuarios WHERE perfil = 'administrador' AND ativo = 1").fetchone()[0]


def alterar(con, login: str, por: str, nome: str | None = None, email: str | None = None,
            perfil: str | None = None, ativo: bool | None = None) -> Usuario:
    u = buscar(con, login)
    if not u:
        raise ErroUsuario("Usuário não encontrado.")
    if perfil is not None and perfil not in PERFIS:
        raise ErroUsuario("Perfil inválido.")
    tira_admin = u.perfil == "administrador" and u.ativo and (
        (perfil is not None and perfil != "administrador") or ativo is False)
    if tira_admin and _administradores_ativos(con) <= 1:
        raise ErroUsuario("É preciso ter pelo menos um administrador ativo.")
    if login == por and ativo is False:
        raise ErroUsuario("Você não pode desativar o seu próprio usuário.")
    novos = {"nome": nome.strip() if nome else None, "email": email, "perfil": perfil,
             "ativo": None if ativo is None else (1 if ativo else 0)}
    novos = {k: v for k, v in novos.items() if v is not None}
    if not novos:
        return u
    antes = {k: getattr(u, k) for k in novos}
    con.execute(f"UPDATE usuarios SET {', '.join(f'{k} = ?' for k in novos)} WHERE login = ?",
                [*novos.values(), login])
    registrar_auditoria(con, por, "usuario_alterado", json.dumps(
        {"login": login, "antes": antes, "depois": novos}, ensure_ascii=False, default=str))
    return buscar(con, login)


def redefinir_senha(con, login: str, por: str) -> str:
    """Gera senha temporária; o usuário é obrigado a trocá-la no próximo acesso."""
    u = buscar(con, login)
    if not u:
        raise ErroUsuario("Usuário não encontrado.")
    temp = gerar_senha_temporaria()
    con.execute("UPDATE usuarios SET senha_hash = ?, trocar_senha = 1, tentativas_falhas = 0, bloqueado_ate = NULL"
                " WHERE login = ?", (gerar_hash(temp), login))
    registrar_auditoria(con, por, "senha_redefinida", json.dumps({"login": login}))
    return temp


def minutos_sessao() -> int:
    """Tempo máximo sem uso antes de pedir login de novo (variável CLOUD_FINANCE_SESSAO_MIN)."""
    try:
        return max(5, int(os.environ.get("CLOUD_FINANCE_SESSAO_MIN", "30")))
    except ValueError:
        return 30
