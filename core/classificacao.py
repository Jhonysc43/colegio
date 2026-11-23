"""Classificação das receitas por regras configuráveis.

Ordem de decisão para cada registro:
1. Classificação manual (por ID Parcela) — sempre prevalece.
2. Regras ativas, da menor para a maior prioridade; a primeira que casar vence.
3. Nenhuma regra casou -> "Não identificado".

O campo "Nº do Pedido" pode trazer vários pedidos separados por vírgula
(ex.: 'RAE001869168,RAE001869170'). A regra de prefixo é testada em cada
pedido; se os pedidos levarem a categorias diferentes, o registro fica como
"Não identificado" para revisão (não escolhemos uma categoria arbitrária).
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from .banco import agora, gravar_config, ler_config, registrar_auditoria

NAO_IDENTIFICADO = "Não identificado"
OPERADORES = {"comeca_com": "começa com", "contem": "contém", "igual": "é igual a"}

# Regras informadas pela usuária em 10/11/2026 (prefixo do Nº do Pedido).
# Prioridade: prefixos mais longos primeiro, para que 'B' (1 letra) não
# capture pedidos de outra categoria que também comecem com B no futuro.
REGRAS_INICIAIS = [
    ("Nº do Pedido", "comeca_com", "INV", "Fatura quinzenal tabelião", 10),
    ("Nº do Pedido", "comeca_com", "RAE", "e-Not Assina", 10),
    ("Nº do Pedido", "comeca_com", "DES", "Desmaterialização e-Not Auto", 10),
    ("Nº do Pedido", "comeca_com", "ENP", "e-Not Provas", 10),
    ("Nº do Pedido", "comeca_com", "RC", "BuscaCEP", 20),
    ("Nº do Pedido", "comeca_com", "B", "BuscaTestamento", 30),
]

# Atualizações de regras confirmadas depois da versão 1. Cada versão é
# aplicada uma única vez em cada banco; se a usuária apagar ou editar a regra
# depois, ela não é recriada.
ATUALIZACOES_REGRAS = {
    2: [("Nº do Pedido", "comeca_com", "DCR", "e-Not Certidões/AEV", 10)],  # confirmada em 10/11/2026
}
VERSAO_REGRAS = max(ATUALIZACOES_REGRAS)

# Receitas agrupadas para os indicadores (confirmado em 10/11/2026: CENSEC = BuscaTestamento).
GRUPOS_INICIAIS = {"BuscaTestamento": "CENSEC"}


@dataclass
class Regra:
    id: int
    campo: str
    operador: str
    valor: str
    categoria: str
    prioridade: int

    def casa(self, texto: str | None) -> bool:
        if texto is None:
            return False
        t = str(texto).strip().upper()
        v = self.valor.strip().upper()
        if self.operador == "comeca_com":
            return t.startswith(v)
        if self.operador == "contem":
            return v in t
        if self.operador == "igual":
            return t == v
        return False


def _inserir_regra(con, campo, op, valor, cat, prio):
    con.execute(
        "INSERT INTO regras_classificacao (campo, operador, valor, categoria, prioridade, ativa, criada_em)"
        " VALUES (?,?,?,?,?,1,?)",
        (campo, op, valor, cat, prio, agora()),
    )


def semear_regras(con) -> None:
    """Cria as regras iniciais (banco novo) e aplica as atualizações pendentes.
    Tudo numa transação: se dois computadores abrirem juntos, o segundo vê o trabalho do primeiro."""
    if (ler_config(con, "versao_regras") == str(VERSAO_REGRAS)
            and ler_config(con, "grupos_semeados") is not None):
        return  # nada a fazer: evita gravar (e trancar o banco) a cada abertura
    from .banco import transacao
    with transacao(con):
        vazio = con.execute("SELECT COUNT(*) FROM regras_classificacao").fetchone()[0] == 0
        versao = int(ler_config(con, "versao_regras", "0" if vazio else "1"))
        if vazio and versao == 0:
            for regra in REGRAS_INICIAIS:
                _inserir_regra(con, *regra)
            versao = 1
        for v in sorted(ATUALIZACOES_REGRAS):
            if v > versao:
                for regra in ATUALIZACOES_REGRAS[v]:
                    _inserir_regra(con, *regra)
                registrar_auditoria(con, "sistema", "atualizacao_regras", f"versão {v}")
                versao = v
        gravar_config(con, "versao_regras", str(versao))
        if ler_config(con, "grupos_semeados") is None:
            for cat, grupo in GRUPOS_INICIAIS.items():
                con.execute("INSERT OR IGNORE INTO grupos_receita (categoria, grupo) VALUES (?,?)", (cat, grupo))
            gravar_config(con, "grupos_semeados", "1")


def carregar_grupos(con) -> dict[str, str]:
    return dict(con.execute("SELECT categoria, grupo FROM grupos_receita").fetchall())


def carregar_regras(con) -> list[Regra]:
    linhas = con.execute(
        "SELECT id, campo, operador, valor, categoria, prioridade FROM regras_classificacao"
        " WHERE ativa = 1 ORDER BY prioridade, LENGTH(valor) DESC, id"
    ).fetchall()
    return [Regra(**dict(l)) for l in linhas]


def _classificar_texto(regras: list[Regra], campos: dict) -> str | None:
    for r in regras:
        valor = campos.get(r.campo)
        if r.campo == "Nº do Pedido" and valor and "," in str(valor):
            partes = [p.strip() for p in str(valor).split(",") if p.strip()]
            if partes and all(r.casa(p) for p in partes):
                return r.categoria
            continue
        if r.casa(valor):
            return r.categoria
    return None


def classificar(regras: list[Regra], dados_originais: dict, manual: str | None = None) -> tuple[str, str]:
    """Retorna (categoria, origem) — origem: 'manual' | 'regra' | 'nao_identificado'."""
    if manual:
        return manual, "manual"
    cat = _classificar_texto(regras, dados_originais)
    if cat:
        return cat, "regra"
    return NAO_IDENTIFICADO, "nao_identificado"


def classificar_registros(con, registros: list[dict]) -> list[dict]:
    """Adiciona 'categoria', 'receita' (grupo) e 'origem_classificacao' a registros de `transacoes`."""
    regras = carregar_regras(con)
    grupos = carregar_grupos(con)
    manuais = dict(con.execute("SELECT id_parcela, categoria FROM classificacoes_manuais").fetchall())
    for r in registros:
        dados = r["dados_originais"]
        if isinstance(dados, str):
            dados = json.loads(dados)
        r["categoria"], r["origem_classificacao"] = classificar(regras, dados, manuais.get(r.get("id_parcela")))
        r["receita"] = grupos.get(r["categoria"], r["categoria"])
    return registros


def definir_manual(con, id_parcela: str, categoria: str, usuario: str | None, motivo: str = "") -> None:
    con.execute(
        "INSERT INTO classificacoes_manuais (id_parcela, categoria, usuario, motivo, definida_em)"
        " VALUES (?,?,?,?,?) ON CONFLICT(id_parcela) DO UPDATE SET categoria=excluded.categoria,"
        " usuario=excluded.usuario, motivo=excluded.motivo, definida_em=excluded.definida_em",
        (id_parcela, categoria, usuario, motivo, agora()),
    )
    registrar_auditoria(con, usuario, "classificacao_manual", json.dumps(
        {"id_parcela": id_parcela, "categoria": categoria, "motivo": motivo}, ensure_ascii=False))
    con.commit()


def remover_manual(con, id_parcela: str, usuario: str | None) -> None:
    con.execute("DELETE FROM classificacoes_manuais WHERE id_parcela = ?", (id_parcela,))
    registrar_auditoria(con, usuario, "classificacao_manual_removida", json.dumps({"id_parcela": id_parcela}))


def validar_regras(regras: list[dict]) -> list[str]:
    erros = []
    for i, r in enumerate(regras, start=1):
        for campo in ("campo", "operador", "valor", "categoria"):
            if not str(r.get(campo) or "").strip():
                erros.append(f"Linha {i}: preencha '{campo}'.")
        if r.get("operador") and r["operador"] not in OPERADORES:
            erros.append(f"Linha {i}: operador inválido.")
        try:
            int(r.get("prioridade"))
        except (TypeError, ValueError):
            erros.append(f"Linha {i}: prioridade deve ser um número inteiro.")
    return erros


def salvar_regras(con, regras: list[dict], usuario: str | None) -> None:
    """Substitui o conjunto de regras (tudo ou nada) e registra antes/depois na auditoria."""
    erros = validar_regras(regras)
    if erros:
        raise ValueError(" ".join(erros))
    antes = [dict(r) for r in con.execute(
        "SELECT campo, operador, valor, categoria, prioridade, ativa FROM regras_classificacao ORDER BY id")]
    from .banco import transacao
    with transacao(con):
        con.execute("DELETE FROM regras_classificacao")
        for r in regras:
            con.execute(
                "INSERT INTO regras_classificacao (campo, operador, valor, categoria, prioridade, ativa, criada_em)"
                " VALUES (?,?,?,?,?,?,?)",
                (r["campo"].strip(), r["operador"], str(r["valor"]).strip(), r["categoria"].strip(),
                 int(r["prioridade"]), 1 if r.get("ativa", True) else 0, agora()))
        registrar_auditoria(con, usuario, "regras_alteradas", json.dumps(
            {"antes": antes, "depois": regras}, ensure_ascii=False, default=str))


def salvar_grupos(con, grupos: dict[str, str], usuario: str | None) -> None:
    from .banco import transacao
    antes = carregar_grupos(con)
    with transacao(con):
        con.execute("DELETE FROM grupos_receita")
        for cat, grupo in grupos.items():
            if str(cat).strip() and str(grupo).strip():
                con.execute("INSERT INTO grupos_receita (categoria, grupo) VALUES (?,?)",
                            (str(cat).strip(), str(grupo).strip()))
        registrar_auditoria(con, usuario, "grupos_alterados", json.dumps(
            {"antes": antes, "depois": grupos}, ensure_ascii=False))


def simular(regras: list[dict], registros_dados: list[dict]) -> dict[str, int]:
    """Quantos registros cada categoria receberia com um conjunto de regras (sem gravar)."""
    objs = [Regra(id=i, campo=r["campo"], operador=r["operador"], valor=str(r["valor"]), categoria=r["categoria"],
                  prioridade=int(r["prioridade"]))
            for i, r in enumerate(regras) if r.get("ativa", True) and not validar_regras([r])]
    objs.sort(key=lambda r: (r.prioridade, -len(r.valor), r.id))
    contagem: dict[str, int] = {}
    for d in registros_dados:
        cat, _ = classificar(objs, d)
        contagem[cat] = contagem.get(cat, 0) + 1
    return contagem
