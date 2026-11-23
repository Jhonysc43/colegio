"""Transações: todos os registros, com escolha de colunas."""
from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from core.formatos import ValorInvalido, formatar_brl, para_centavos

from .comum import aviso_sem_dados, card, colunas_originais, dados_filtrados, inteiro, texto_periodo

CALCULADAS = {"data_entrada": "Data de entrada", "receita": "Receita", "categoria": "Categoria",
              "origem_classificacao": "Origem da classificação", "meio": "Meio (sistema)"}
PADRAO = ["Data de entrada", "Receita", "Meio (sistema)", "ID Parcela", "Nº do Pedido", "Forma de Pagamento",
          "Valor Bruto", "Custo Financeiro", "Valor Líquido", "Data de Pagamento", "Pagador", "Status do Lote"]
ORIGEM = {"regra": "Regra", "manual": "Manual", "nao_identificado": "—"}
LIMITE_TELA = 20000


def pagina(con):
    df_total, df, f = dados_filtrados(con)
    st.title("Transações")
    if aviso_sem_dados(df_total):
        return
    st.caption(f"Período: **{texto_periodo(f, df_total)}** · uma linha por registro da planilha, com os valores "
               "originais. Colunas calculadas pelo sistema: Data de entrada, Receita, Categoria, Meio.")
    if df.empty:
        st.warning("Nenhum registro atende aos filtros selecionados.")
        return

    c = st.columns(4)
    with c[0]: card("Registros", inteiro(len(df)))
    with c[1]: card("Pagamentos", inteiro(df["id_parcela"].nunique()))
    with c[2]: card("Valor bruto", formatar_brl(df["valor_bruto_cent"].sum()))
    with c[3]: card("Valor líquido", formatar_brl(df["valor_liquido_cent"].sum()))

    originais = colunas_originais(con)
    todas = list(CALCULADAS.values()) + originais
    escolhidas = st.multiselect("Colunas exibidas", todas, default=[c for c in PADRAO if c in todas],
                                key="tr_colunas")
    busca = st.text_input("Buscar em qualquer coluna", key="tr_busca",
                          placeholder="Ex.: nome do pagador, nº do documento...")

    base = df.sort_values(["data_entrada", "id"])
    dados = pd.DataFrame(list(base["dados_originais"].map(json.loads)), index=base.index)
    tabela = pd.concat([base[list(CALCULADAS)].rename(columns=CALCULADAS), dados], axis=1)
    tabela["Data de entrada"] = pd.to_datetime(tabela["Data de entrada"]).dt.strftime("%d/%m/%Y")
    tabela["Origem da classificação"] = tabela["Origem da classificação"].map(ORIGEM)
    if busca.strip():
        alvo = busca.strip().lower()
        mask = tabela.astype(str).apply(lambda col: col.str.lower().str.contains(alvo, regex=False)).any(axis=1)
        tabela = tabela[mask]
        st.caption(f"{inteiro(len(tabela))} registro(s) encontrados.")
    cols = escolhidas or todas
    if len(tabela) > LIMITE_TELA:
        st.info(f"Mostrando os primeiros {inteiro(LIMITE_TELA)} de {inteiro(len(tabela))} registros. "
                "Use os filtros ou exporte em Relatórios para ver todos.")
    exibir = tabela[cols].head(LIMITE_TELA).copy()
    for c in ("Valor Bruto", "Custo Financeiro", "Valor Líquido"):
        if c in exibir:
            exibir[c] = exibir[c].map(_brl)
    st.dataframe(exibir, hide_index=True, height=560)


def _brl(v):
    """Exibe em R$ 1.234,56; se o valor original não for numérico, mostra como veio."""
    try:
        return formatar_brl(para_centavos(v))
    except ValorInvalido:
        return v
