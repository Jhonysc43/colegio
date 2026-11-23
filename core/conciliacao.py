"""Conferência e conciliação.

Todas as verificações SINALIZAM: nenhum valor original é alterado. A única
alteração possível é a resolução de um conflito, sempre por decisão explícita
da usuária e registrada na auditoria.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd

from .banco import agora, registrar_auditoria, transacao
from .classificacao import NAO_IDENTIFICADO
from .importacao import COLUNAS_FORA_DO_HASH, _normalizar_para_hash, campos_de_dados
from .indicadores import MEIOS, resumo, resumo_por


@dataclass
class Verificacao:
    codigo: str
    titulo: str
    descricao: str
    gravidade: str          # 'erro' | 'atencao' | 'info'
    registros: pd.DataFrame

    @property
    def quantidade(self) -> int:
        return len(self.registros)


def _vazio(df: pd.DataFrame) -> pd.DataFrame:
    return df.iloc[0:0]


def divergencias_valor(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    calc = df["valor_bruto_cent"] - df["custo_financeiro_cent"]
    out = df[calc != df["valor_liquido_cent"]].copy()
    out["diferenca_cent"] = (out["valor_bruto_cent"] - out["custo_financeiro_cent"]) - out["valor_liquido_cent"]
    return out


def valores_ausentes_ou_negativos(df: pd.DataFrame, con=None) -> pd.DataFrame:
    if df.empty:
        return df
    cols = ["valor_bruto_cent", "custo_financeiro_cent", "valor_liquido_cent"]
    # carregar_dataframe preenche vazios com 0; a ausência real é lida do banco
    if con is not None:
        ids = {r[0] for r in con.execute(
            "SELECT id FROM transacoes WHERE valor_bruto_cent IS NULL OR custo_financeiro_cent IS NULL"
            " OR valor_liquido_cent IS NULL")}
        aus = df["id"].isin(ids)
    else:
        aus = pd.Series(False, index=df.index)
    return df[aus | (df[cols] < 0).any(axis=1)]


def parcela_em_varias_datas(df: pd.DataFrame) -> pd.DataFrame:
    """Mesmo ID Parcela com data de entrada diferente: possível pagamento importado em dias distintos."""
    if df.empty:
        return df
    n = df.groupby("id_parcela")["data_entrada"].nunique()
    return df[df["id_parcela"].isin(n[n > 1].index)].sort_values(["id_parcela", "data_entrada"])


def linhas_identicas(df: pd.DataFrame) -> pd.DataFrame:
    """Linhas iguais em tudo, exceto ID da Venda. Pode ser split legítimo (ex.: várias linhas
    de R$ 0,12 no mesmo pagamento) — exibido apenas para conferência."""
    if df.empty:
        return df
    def sem_venda(s):
        d = json.loads(s)
        d.pop("ID da Venda", None)
        d.pop("Sistemas", None)
        return json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
    chave = df["dados_originais"].map(sem_venda)
    return df[chave.duplicated(keep=False)].sort_values(["id_parcela", "id"])


def sem_classificacao(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["categoria"] == NAO_IDENTIFICADO] if not df.empty else df


def classificacao_difere_da_planilha(df: pd.DataFrame) -> pd.DataFrame:
    """Categoria calculada pelo sistema diferente da coluna "Sistemas" da planilha (quando preenchida)."""
    if df.empty or "sistemas_planilha" not in df:
        return _vazio(df)
    tem = df["sistemas_planilha"].notna() & (df["sistemas_planilha"].astype(str).str.strip() != "")
    return df[tem & (df["categoria"] != df["sistemas_planilha"])]


def status_nao_pago(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["status_lote"].fillna("").str.strip().str.lower() != "pago"]


def lotes_com_status_diferentes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    n = df.groupby("id_lote")["status_lote"].nunique()
    return df[df["id_lote"].isin(n[n > 1].index)]


def datas_inconsistentes(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    motivos = pd.Series("", index=df.index)
    def marca(mask, texto):
        nonlocal motivos
        motivos = motivos.where(~mask, motivos + "; " + texto)
    sem_pag = df["data_pagamento"].isna()
    marca(sem_pag, "sem data de pagamento")
    marca(df["data_pagamento"].notna() & (df["data_pagamento"] > df["data_entrada"]),
          "pagamento depois da data de entrada")
    marca(df["data_liquidacao"].notna() & (df["data_liquidacao"] != df["data_entrada"]),
          "liquidação da planilha diferente da data de entrada")
    marca(df["data_liquidacao"].notna() & df["data_pagamento"].notna()
          & (df["data_liquidacao"] < df["data_pagamento"]), "liquidação antes do pagamento")
    out = df[motivos != ""].copy()
    out["motivo"] = motivos[motivos != ""].str.lstrip("; ")
    return out


def pagamento_anterior_a_criacao(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df[df["data_pagamento"].notna() & df["data_criacao"].notna()
              & (df["data_pagamento"] < df["data_criacao"])]


def parcelas_do_mesmo_pedido(df: pd.DataFrame) -> pd.DataFrame:
    """Pedidos com mais de um ID Parcela, e linhas que reúnem vários pedidos no mesmo campo."""
    if df.empty:
        return df
    n = df.groupby("nr_pedido")["id_parcela"].nunique()
    varias = df["nr_pedido"].isin(n[n > 1].index)
    multiplos = df["nr_pedido"].fillna("").str.contains(",")
    out = df[varias | multiplos].copy()
    out["motivo"] = ["vários pedidos na mesma parcela" if m else "pedido com mais de uma parcela"
                     for m in multiplos[varias | multiplos]]
    return out.sort_values(["nr_pedido", "id_parcela"])


def conflitos_pendentes(con) -> pd.DataFrame:
    linhas = con.execute(
        "SELECT c.id, c.importacao_id, c.chave_registro, c.linha_planilha, c.dados_originais AS dados_novos,"
        " i.arquivo, i.processado_em, t.dados_originais AS dados_atuais, t.id AS transacao_id"
        " FROM conflitos c JOIN importacoes i ON i.id = c.importacao_id"
        " LEFT JOIN transacoes t ON t.chave_registro = c.chave_registro"
        " WHERE c.situacao = 'pendente' ORDER BY c.id").fetchall()
    return pd.DataFrame([dict(l) for l in linhas])


def diferencas_conflito(dados_atuais: str, dados_novos: str) -> pd.DataFrame:
    a = json.loads(dados_atuais) if isinstance(dados_atuais, str) and dados_atuais else {}
    n = json.loads(dados_novos)
    # mesma regra da importação: vazio == texto vazio; colunas auxiliares (fórmulas) não contam
    linhas = [{"Coluna": k, "Valor atual": a.get(k), "Valor novo": n.get(k)}
              for k in dict.fromkeys(list(a) + list(n))
              if k not in COLUNAS_FORA_DO_HASH and _normalizar_para_hash(a.get(k)) != _normalizar_para_hash(n.get(k))]
    return pd.DataFrame(linhas)


DECISOES = {"mantido_original": "Manter o registro atual",
            "substituido": "Substituir pelo registro novo",
            "ambos": "Manter os dois (são pagamentos diferentes)"}


def resolver_conflito(con, conflito_id: int, decisao: str, usuario: str | None) -> None:
    if decisao not in DECISOES:
        raise ValueError(f"Decisão inválida: {decisao}")
    c = con.execute("SELECT * FROM conflitos WHERE id = ? AND situacao = 'pendente'", (conflito_id,)).fetchone()
    if not c:
        raise ValueError("Conflito não encontrado ou já resolvido.")
    dados = json.loads(c["dados_originais"])
    campos = campos_de_dados(dados)
    imp = con.execute("SELECT data_entrada FROM importacoes WHERE id = ?", (c["importacao_id"],)).fetchone()
    with transacao(con):
        anterior = con.execute("SELECT * FROM transacoes WHERE chave_registro = ?", (c["chave_registro"],)).fetchone()
        if anterior is None and decisao != "mantido_original":
            # o registro atual foi removido (ex.: exclusão da importação original): grava o novo
            nova = {**campos, "importacao_id": c["importacao_id"], "linha_planilha": c["linha_planilha"],
                    "chave_registro": c["chave_registro"], "data_entrada": imp["data_entrada"]}
            con.execute(f"INSERT INTO transacoes ({', '.join(nova)}) VALUES ({', '.join('?' * len(nova))})",
                        list(nova.values()))
        elif decisao == "substituido":
            sets = ", ".join(f"{k} = ?" for k in campos)
            con.execute(f"UPDATE transacoes SET {sets}, importacao_id = ?, linha_planilha = ?"
                        " WHERE chave_registro = ?",
                        [*campos.values(), c["importacao_id"], c["linha_planilha"], c["chave_registro"]])
        elif decisao == "ambos":
            nova = {**campos, "importacao_id": c["importacao_id"], "linha_planilha": c["linha_planilha"],
                    "chave_registro": f"{c['chave_registro']}#conflito{conflito_id}",
                    "data_entrada": imp["data_entrada"]}
            con.execute(f"INSERT INTO transacoes ({', '.join(nova)}) VALUES ({', '.join('?' * len(nova))})",
                        list(nova.values()))
        con.execute("UPDATE conflitos SET situacao = ?, decidido_por = ?, decidido_em = ? WHERE id = ?",
                    (decisao, usuario, agora(), conflito_id))
        registrar_auditoria(con, usuario, "resolucao_conflito", json.dumps({
            "conflito_id": conflito_id, "chave": c["chave_registro"], "decisao": decisao,
            "registro_anterior": dict(anterior)["dados_originais"] if anterior else None}, ensure_ascii=False))


def conferencia_composicao(df: pd.DataFrame) -> pd.DataFrame:
    """Confere se os totais do Dashboard fecham: total = soma por meio = soma por receita = soma por dia."""
    r = resumo(df)
    linhas = []
    for nome, col in (("Meio de pagamento", "meio"), ("Receita", "receita"), ("Data de entrada", "data_entrada")):
        p = resumo_por(df, col) if not df.empty else pd.DataFrame(columns=["bruto_cent", "custo_cent",
                                                                            "liquido_cent", "pagamentos"])
        for medida, k in (("Valor bruto", "bruto_cent"), ("Custo financeiro", "custo_cent"),
                          ("Valor líquido", "liquido_cent")):
            soma = int(p[k].sum()) if not p.empty else 0
            linhas.append({"Composição": f"Soma por {nome.lower()}", "Medida": medida,
                           "unidade": "R$", "total": r[k], "partes": soma, "Confere": soma == r[k]})
        # pagamentos: cada pagamento deve pertencer a um único grupo
        soma_p = int(p["pagamentos"].sum()) if not p.empty else 0
        linhas.append({"Composição": f"Soma por {nome.lower()}", "Medida": "Pagamentos",
                       "unidade": "qtd", "total": r["pagamentos"], "partes": soma_p,
                       "Confere": soma_p == r["pagamentos"]})
    if not df.empty:
        fora = df[~df["meio"].isin(MEIOS)]
        linhas.append({"Composição": "Registros fora de Pix/Cartão/Boleto", "Medida": "Registros",
                       "unidade": "qtd", "total": 0, "partes": len(fora), "Confere": fora.empty})
    return pd.DataFrame(linhas)


def executar_verificacoes(con, df: pd.DataFrame) -> list[Verificacao]:
    v = [
        Verificacao("divergencia", "Líquido diferente de Bruto − Custo",
                    "Registros em que Valor Líquido ≠ Valor Bruto − Custo Financeiro.", "erro",
                    divergencias_valor(df)),
        Verificacao("valores", "Valores ausentes ou negativos", "Bruto, custo ou líquido vazio ou negativo.",
                    "erro", valores_ausentes_ou_negativos(df, con)),
        Verificacao("sem_classificacao", "Sem classificação", "Registros classificados como \"Não identificado\".",
                    "atencao", sem_classificacao(df)),
        Verificacao("classificacao_planilha", "Classificação diferente da coluna Sistemas",
                    "A categoria do sistema difere da fórmula \"Sistemas\" da planilha.", "atencao",
                    classificacao_difere_da_planilha(df)),
        Verificacao("parcela_datas", "Mesmo pagamento em datas de entrada diferentes",
                    "O mesmo ID Parcela foi importado em mais de uma data de entrada — possível duplicidade.",
                    "atencao", parcela_em_varias_datas(df)),
        Verificacao("status", "Status do lote diferente de \"Pago\"",
                    "Registros cujo lote não está como Pago.", "atencao", status_nao_pago(df)),
        Verificacao("lote_status", "Lotes com status diferentes", "O mesmo ID do Lote aparece com mais de um status.",
                    "atencao", lotes_com_status_diferentes(df)),
        Verificacao("datas", "Datas inconsistentes",
                    "Sem data de pagamento, pagamento depois da entrada, liquidação diferente da entrada etc.",
                    "atencao", datas_inconsistentes(df)),
        Verificacao("pag_criacao", "Pagamento anterior à criação da linha",
                    "Comum em linhas de split confirmadas depois do pagamento.", "info",
                    pagamento_anterior_a_criacao(df)),
        Verificacao("mesmo_pedido", "Parcelas vinculadas ao mesmo pedido",
                    "Pedido com mais de uma parcela, ou vários pedidos no mesmo campo.", "info",
                    parcelas_do_mesmo_pedido(df)),
        Verificacao("identicas", "Linhas idênticas (exceto ID da Venda)",
                    "Podem ser split legítimo; não são somadas em dobro, pois cada linha tem ID da Venda próprio.",
                    "info", linhas_identicas(df)),
    ]
    return v
