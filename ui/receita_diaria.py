"""Receita Diária."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.formatos import formatar_brl, formatar_data
from core.indicadores import receita_diaria, resumo, resumo_por, totais_por_dia

from .comum import (aviso_sem_dados, card, dados_filtrados, extrair_original, inteiro, pct, tabela_formatada,
                    texto_periodo)

MOEDAS = ("bruto_cent", "custo_cent", "liquido_cent")
NOMES = {"data_entrada": "Data", "receita": "Receita", "pagamentos": "Pagamentos", "bruto_cent": "Valor bruto",
         "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido", "qtd_pix": "Pix",
         "qtd_cartao": "Cartões", "qtd_boleto": "Boletos"}


def pagina(con):
    df_total, df, f = dados_filtrados(con)
    st.title("Receita Diária")
    if aviso_sem_dados(df_total):
        return
    st.caption(f"Período: **{texto_periodo(f, df_total)}** · os filtros da barra lateral valem para esta tela.")
    if df.empty:
        st.warning("Nenhum registro atende aos filtros selecionados.")
        return

    totais = totais_por_dia(df)
    st.subheader("Totais por dia")
    t = totais.copy()
    t["var_bruto"] = t["var_bruto_pct"].map(pct)
    t["var_pag"] = t["var_pagamentos_pct"].map(pct)
    st.dataframe(tabela_formatada(t, {**{k: v for k, v in NOMES.items() if k != "receita"},
                                      "var_bruto": "Var. bruto (dia anterior)",
                                      "var_pag": "Var. pagamentos (dia anterior)"},
                                  moedas=MOEDAS, datas=("data_entrada",)), hide_index=True)

    st.subheader("Por dia e receita")
    st.dataframe(tabela_formatada(receita_diaria(df), NOMES, moedas=MOEDAS, datas=("data_entrada",)),
                 hide_index=True)

    # ------------------------------------------------------- detalhe de um dia
    st.subheader("Detalhar um dia")
    datas = sorted(df["data_entrada"].unique(), reverse=True)
    dia = st.selectbox("Data", datas, format_func=formatar_data, key="rd_dia")
    d = df[df["data_entrada"] == dia]
    r = resumo(d)
    c = st.columns(4)
    with c[0]: card("Pagamentos", inteiro(r["pagamentos"]), f"{inteiro(r['registros'])} linhas")
    with c[1]: card("Valor bruto", formatar_brl(r["bruto_cent"]))
    with c[2]: card("Custo financeiro", formatar_brl(r["custo_cent"]))
    with c[3]: card("Valor líquido", formatar_brl(r["liquido_cent"]))
    det = extrair_original(d, ["Pagador", "Descrição"])
    st.dataframe(_detalhe(det), hide_index=True)

    # ------------------------------------------------------- comparar duas datas
    st.subheader("Comparar datas")
    if len(datas) < 2:
        st.caption("A comparação fica disponível quando houver pelo menos duas datas de entrada importadas.")
        return
    c1, c2 = st.columns(2)
    a = c1.selectbox("Data A", datas, index=1, format_func=formatar_data, key="rd_a")
    b = c2.selectbox("Data B", datas, index=0, format_func=formatar_data, key="rd_b")
    ra, rb = resumo(df[df["data_entrada"] == a]), resumo(df[df["data_entrada"] == b])
    cols = st.columns(4)
    for col, (rot, k, moeda) in zip(cols, [("Pagamentos", "pagamentos", False), ("Valor bruto", "bruto_cent", True),
                                           ("Custo financeiro", "custo_cent", True),
                                           ("Valor líquido", "liquido_cent", True)]):
        fmt = formatar_brl if moeda else inteiro
        dif = rb[k] - ra[k]
        var = pct(dif / ra[k] * 100) if ra[k] else "—"
        col.metric(f"{rot} ({formatar_data(b)})", fmt(rb[k]),
                   delta=f"{fmt(dif) if moeda else f'{dif:+d}'} ({var}) vs {formatar_data(a)}",
                   delta_color="off" if k == "custo_cent" else "normal")
    comp = resumo_por(df[df["data_entrada"].isin([a, b])], ["receita", "data_entrada"])
    comp = comp.pivot_table(index="receita", columns="data_entrada", values="bruto_cent", aggfunc="sum",
                            fill_value=0).reindex(columns=[a, b], fill_value=0).reset_index()
    comp.columns.name = None
    comp["dif"] = comp[b] - comp[a]
    st.dataframe(tabela_formatada(comp, {"receita": "Receita", a: f"Bruto {formatar_data(a)}",
                                         b: f"Bruto {formatar_data(b)}", "dif": "Diferença"},
                                  moedas=(a, b, "dif")), hide_index=True)


def _detalhe(det: pd.DataFrame) -> pd.DataFrame:
    return tabela_formatada(det.sort_values(["receita", "id_parcela"]), {
        "id_parcela": "ID Parcela", "nr_pedido": "Nº do Pedido", "receita": "Receita", "meio": "Meio",
        "forma_pagamento": "Forma de pagamento", "Pagador": "Pagador", "valor_bruto_cent": "Valor bruto",
        "custo_financeiro_cent": "Custo financeiro", "valor_liquido_cent": "Valor líquido",
        "data_pagamento": "Data de pagamento", "status_lote": "Status do lote", "linha_planilha": "Linha no Excel"},
        moedas=("valor_bruto_cent", "custo_financeiro_cent", "valor_liquido_cent"), datas=("data_pagamento",))
