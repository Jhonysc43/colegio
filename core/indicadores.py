"""Cálculo dos indicadores financeiros.

Regras confirmadas pela usuária em 10/11/2026:
- Todos os registros importados contam como receita recebida.
- A data de referência é a "data de entrada" informada na importação.
- Quantidade de pagamentos = nº de ID Parcela DISTINTOS. As linhas de split do
  mesmo pagamento somam nos valores, mas o pagamento conta uma vez.
- Cartão: cada pedido é pago uma única vez (sem contagem por parcela).
- Meio de pagamento exibido (Pix / Cartão / Boleto):
    "Meio de Pagamento" contém "Boleto" (ex.: Boleto Híbrido) -> Boleto,
    mesmo quando a "Forma de Pagamento" foi PIX;
    senão, Forma PIX -> Pix; Crédito/Débito -> Cartão; Forma Boleto -> Boleto.
- Receita "CENSEC" = categoria BuscaTestamento (tabela grupos_receita).

Quando um pagamento tem linhas em grupos diferentes, ele conta uma vez em
cada grupo, mas apenas uma vez no total geral.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, fields

import pandas as pd

from .banco import gravar_config, ler_config, registrar_auditoria
from .classificacao import classificar_registros

MEIOS = ["Pix", "Cartão", "Boleto"]


def meio_exibicao(forma: str | None, meio: str | None = None) -> str:
    m = str(meio or "").strip().upper()
    f = str(forma or "").strip().upper()
    if "BOLETO" in m:
        return "Boleto"
    if f == "PIX":
        return "Pix"
    if f.startswith(("CRÉDITO", "CREDITO", "DÉBITO", "DEBITO")):
        return "Cartão"
    if f == "BOLETO":
        return "Boleto"
    if not f and not m:
        return "Não informado"
    return f"Outro ({forma or meio})"


def carregar_dataframe(con, data_inicio: str | None = None, data_fim: str | None = None) -> pd.DataFrame:
    sql = "SELECT * FROM transacoes WHERE 1=1"
    params: list = []
    if data_inicio:
        sql += " AND data_entrada >= ?"
        params.append(data_inicio)
    if data_fim:
        sql += " AND data_entrada <= ?"
        params.append(data_fim)
    registros = [dict(r) for r in con.execute(sql + " ORDER BY data_entrada, id", params)]
    registros = classificar_registros(con, registros)
    df = pd.DataFrame(registros)
    if df.empty:
        return df
    df["meio"] = [meio_exibicao(f, m) for f, m in zip(df["forma_pagamento"], df["meio_pagamento"])]
    for c in ("valor_bruto_cent", "custo_financeiro_cent", "valor_liquido_cent"):
        df[c] = df[c].fillna(0).astype("int64")
    return df


# ------------------------------------------------- regra de inclusão por status
# Regra confirmada em 10/11/2026: todos os registros contam como receita recebida.
# A usuária pode, em Configurações, retirar dos indicadores registros de certos
# status (ex.: "Cancelado", "Estornado"). Eles continuam no banco e na Conciliação.
def status_excluidos(con) -> list[str]:
    return json.loads(ler_config(con, "status_excluidos", "[]"))


def definir_status_excluidos(con, status: list[str], usuario: str | None) -> None:
    gravar_config(con, "status_excluidos", json.dumps(sorted(status), ensure_ascii=False))
    registrar_auditoria(con, usuario, "regra_inclusao_status", json.dumps(sorted(status), ensure_ascii=False))


def aplicar_regra_inclusao(df: pd.DataFrame, excluidos: list[str]) -> pd.DataFrame:
    if df.empty or not excluidos:
        return df
    return df[~df["status_lote"].fillna("(vazio)").isin(excluidos)]


# --------------------------------------------------------------------- filtros
@dataclass
class Filtros:
    entrada_ini: str | None = None        # AAAA-MM-DD
    entrada_fim: str | None = None
    pagamento_ini: str | None = None
    pagamento_fim: str | None = None
    liquidacao_ini: str | None = None
    liquidacao_fim: str | None = None
    receitas: list[str] = field(default_factory=list)
    meios: list[str] = field(default_factory=list)
    formas: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)
    estabelecimentos: list[str] = field(default_factory=list)
    sistemas: list[str] = field(default_factory=list)
    id_lote: str = ""
    id_parcela: str = ""
    nr_pedido: str = ""

    def ativos(self) -> int:
        return sum(1 for f in fields(self) if getattr(self, f.name))


def _entre(serie: pd.Series, ini: str | None, fim: str | None) -> pd.Series:
    m = pd.Series(True, index=serie.index)
    if ini:
        m &= serie.fillna("") >= ini
    if fim:
        m &= serie.fillna("9999") <= fim
    return m


def aplicar_filtros(df: pd.DataFrame, f: Filtros) -> pd.DataFrame:
    if df.empty:
        return df
    m = _entre(df["data_entrada"], f.entrada_ini, f.entrada_fim)
    m &= _entre(df["data_pagamento"], f.pagamento_ini, f.pagamento_fim)
    m &= _entre(df["data_liquidacao"], f.liquidacao_ini, f.liquidacao_fim)
    for valores, col in ((f.receitas, "receita"), (f.meios, "meio"), (f.formas, "forma_pagamento"),
                         (f.status, "status_lote"), (f.estabelecimentos, "estabelecimento"),
                         (f.sistemas, "sistemas_planilha")):
        if valores:
            m &= df[col].isin(valores)
    for texto, col in ((f.id_lote, "id_lote"), (f.id_parcela, "id_parcela"), (f.nr_pedido, "nr_pedido")):
        if texto.strip():
            m &= df[col].fillna("").astype(str).str.contains(texto.strip(), case=False, regex=False)
    return df[m]


# ------------------------------------------------------------------ agregações
def resumo(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"pagamentos": 0, "registros": 0, "bruto_cent": 0, "custo_cent": 0, "liquido_cent": 0}
    return {
        "pagamentos": int(df["id_parcela"].nunique()),
        "registros": int(len(df)),
        "bruto_cent": int(df["valor_bruto_cent"].sum()),
        "custo_cent": int(df["custo_financeiro_cent"].sum()),
        "liquido_cent": int(df["valor_liquido_cent"].sum()),
    }


COLS_RESUMO = ["pagamentos", "registros", "bruto_cent", "custo_cent", "liquido_cent"]


def resumo_por(df: pd.DataFrame, colunas: str | list[str]) -> pd.DataFrame:
    colunas = [colunas] if isinstance(colunas, str) else list(colunas)
    if df.empty:
        return pd.DataFrame(columns=colunas + COLS_RESUMO)
    g = df.groupby(colunas, dropna=False)
    out = pd.DataFrame({
        "pagamentos": g["id_parcela"].nunique(),
        "registros": g.size(),
        "bruto_cent": g["valor_bruto_cent"].sum(),
        "custo_cent": g["custo_financeiro_cent"].sum(),
        "liquido_cent": g["valor_liquido_cent"].sum(),
    }).reset_index()
    return out


def _contagem_meios(df: pd.DataFrame, chaves: list[str]) -> pd.DataFrame:
    """Qtd. de pagamentos (ID Parcela distintos) por meio, em colunas qtd_pix/qtd_cartao/qtd_boleto."""
    nomes = {"Pix": "qtd_pix", "Cartão": "qtd_cartao", "Boleto": "qtd_boleto"}
    base = df[df["meio"].isin(nomes)]
    if base.empty:
        t = df[chaves].drop_duplicates().copy()
        for c in nomes.values():
            t[c] = 0
        return t
    t = base.groupby(chaves + ["meio"])["id_parcela"].nunique().unstack("meio", fill_value=0)
    t = t.rename(columns=nomes).reset_index()
    for c in nomes.values():
        if c not in t:
            t[c] = 0
    return t[chaves + list(nomes.values())]


def receita_diaria(df: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por data de entrada × receita."""
    if df.empty:
        return pd.DataFrame(columns=["data_entrada", "receita"] + COLS_RESUMO + ["qtd_pix", "qtd_cartao", "qtd_boleto"])
    chaves = ["data_entrada", "receita"]
    t = resumo_por(df, chaves).merge(_contagem_meios(df, chaves), on=chaves, how="left")
    for c in ("qtd_pix", "qtd_cartao", "qtd_boleto"):
        t[c] = t[c].fillna(0).astype(int)
    return t.sort_values(["data_entrada", "bruto_cent"], ascending=[True, False], ignore_index=True)


def totais_por_dia(df: pd.DataFrame) -> pd.DataFrame:
    """Totais de cada data de entrada, com variação em relação à data anterior."""
    if df.empty:
        return pd.DataFrame(columns=["data_entrada"] + COLS_RESUMO + ["qtd_pix", "qtd_cartao", "qtd_boleto",
                                                                      "var_bruto_pct", "var_pagamentos_pct"])
    t = resumo_por(df, "data_entrada").merge(_contagem_meios(df, ["data_entrada"]), on="data_entrada", how="left")
    t = t.fillna(0).sort_values("data_entrada", ignore_index=True)
    ant_b, ant_p = t["bruto_cent"].shift(1), t["pagamentos"].shift(1)
    t["var_bruto_pct"] = ((t["bruto_cent"] - ant_b) / ant_b.where(ant_b != 0) * 100).round(1)
    t["var_pagamentos_pct"] = ((t["pagamentos"] - ant_p) / ant_p.where(ant_p != 0) * 100).round(1)
    return t


def boletos_por_dia(df: pd.DataFrame) -> pd.DataFrame:
    """Boletos (meio = Boleto) por data de entrada, com lotes, status e forma de quitação."""
    cols = ["data_entrada"] + COLS_RESUMO + ["pagos_via_boleto", "pagos_via_pix", "status_lote", "lotes"]
    b = df[df["meio"] == "Boleto"] if not df.empty else df
    if b.empty:
        return pd.DataFrame(columns=cols)
    t = resumo_por(b, "data_entrada")
    g = b.groupby("data_entrada")
    forma = b.assign(f=b["forma_pagamento"].fillna("").str.upper())
    t = t.merge(forma[forma.f == "BOLETO"].groupby("data_entrada")["id_parcela"].nunique()
                .rename("pagos_via_boleto").reset_index(), on="data_entrada", how="left")
    t = t.merge(forma[forma.f == "PIX"].groupby("data_entrada")["id_parcela"].nunique()
                .rename("pagos_via_pix").reset_index(), on="data_entrada", how="left")
    t = t.merge(g["status_lote"].agg(lambda s: ", ".join(sorted(s.dropna().astype(str).unique())))
                .rename("status_lote").reset_index(), on="data_entrada")
    t = t.merge(g["id_lote"].agg(lambda s: sorted(s.dropna().astype(str).unique()))
                .rename("lotes").reset_index(), on="data_entrada")
    t[["pagos_via_boleto", "pagos_via_pix"]] = t[["pagos_via_boleto", "pagos_via_pix"]].fillna(0).astype(int)
    return t[cols].sort_values("data_entrada", ignore_index=True)
