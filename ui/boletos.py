"""Boletos Processados."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.formatos import formatar_brl, formatar_data
from core.indicadores import boletos_por_dia, resumo

from .comum import (CORES_MEIO, aviso_sem_dados, card, dados_filtrados, extrair_original, inteiro, layout_grafico,
                    mostrar_grafico, tabela_formatada, texto_periodo)

MOEDAS = ("bruto_cent", "custo_cent", "liquido_cent")


def _por_boleto(b: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por boleto (ID Parcela), somando as linhas de split."""
    b = extrair_original(b, ["Pagador", "Nº do documento"])
    g = b.groupby("id_parcela", dropna=False)
    out = g.agg(nr_pedido=("nr_pedido", "first"), receita=("receita", "first"), Pagador=("Pagador", "first"),
                documento=("Nº do documento", "first"), forma=("forma_pagamento", "first"),
                data_criacao=("data_criacao", "min"), data_pagamento=("data_pagamento", "max"),
                data_liquidacao=("data_liquidacao", "max"), data_entrada=("data_entrada", "max"),
                status_lote=("status_lote", lambda s: ", ".join(sorted(s.dropna().astype(str).unique()))),
                id_lote=("id_lote", "first"), linhas=("id", "size"),
                bruto_cent=("valor_bruto_cent", "sum"), custo_cent=("custo_financeiro_cent", "sum"),
                liquido_cent=("valor_liquido_cent", "sum")).reset_index()
    return out.sort_values(["receita", "id_parcela"], ignore_index=True)


NOMES_BOLETO = {
    "id_parcela": "ID Parcela", "nr_pedido": "Nº do Pedido", "receita": "Receita", "Pagador": "Pagador",
    "documento": "Nº do documento", "forma": "Quitado via", "data_criacao": "Data de criação",
    "data_pagamento": "Data de pagamento", "data_liquidacao": "Data de liquidação",
    "data_entrada": "Data de processamento", "bruto_cent": "Valor bruto", "custo_cent": "Custo financeiro",
    "liquido_cent": "Valor líquido", "status_lote": "Status do lote", "id_lote": "ID do Lote", "linhas": "Linhas"}
DATAS_BOLETO = ("data_criacao", "data_pagamento", "data_liquidacao", "data_entrada")


def pagina(con):
    df_total, df, f = dados_filtrados(con)
    st.title("Boletos Processados")
    if aviso_sem_dados(df_total):
        return
    st.caption(f"Período: **{texto_periodo(f, df_total)}** · Boleto = Meio de Pagamento \"Boleto Híbrido\", "
               "inclusive quando quitado via Pix · Data de processamento = data de entrada informada na importação.")
    b = df[df["meio"] == "Boleto"] if not df.empty else df
    if b.empty:
        st.warning("Nenhum boleto atende aos filtros selecionados.")
        return

    dia = boletos_por_dia(b)
    r = resumo(b)
    c = st.columns(5)
    with c[0]: card("Boletos", inteiro(r["pagamentos"]), f"{inteiro(r['registros'])} linhas")
    with c[1]: card("Quitados via boleto / via Pix",
                    f"{inteiro(dia['pagos_via_boleto'].sum())} / {inteiro(dia['pagos_via_pix'].sum())}")
    with c[2]: card("Valor bruto", formatar_brl(r["bruto_cent"]))
    with c[3]: card("Custo financeiro", formatar_brl(r["custo_cent"]))
    with c[4]: card("Valor líquido", formatar_brl(r["liquido_cent"]))

    st.subheader("Por data de processamento")
    t = dia.copy()
    t["qtd_lotes"] = t["lotes"].map(len)
    t["lotes_txt"] = t["lotes"].map(lambda ls: ", ".join(ls))
    st.dataframe(tabela_formatada(t, {
        "data_entrada": "Data de processamento", "pagamentos": "Qtd. boletos", "pagos_via_boleto": "Via boleto",
        "pagos_via_pix": "Via Pix", "bruto_cent": "Valor bruto", "custo_cent": "Custo financeiro",
        "liquido_cent": "Valor líquido", "status_lote": "Status do lote", "qtd_lotes": "Lotes",
        "lotes_txt": "ID do Lote"}, moedas=MOEDAS, datas=("data_entrada",)), hide_index=True)

    t["data_fmt"] = t["data_entrada"].map(formatar_data)
    g1, g2 = st.columns(2)
    with g1:
        fig = go.Figure()
        fig.add_bar(x=t["data_fmt"], y=t["pagos_via_boleto"], name="Quitado via boleto",
                    marker_color=CORES_MEIO["Boleto"], hovertemplate="%{x}<br>%{y} via boleto<extra></extra>")
        fig.add_bar(x=t["data_fmt"], y=t["pagos_via_pix"], name="Quitado via Pix",
                    marker_color=CORES_MEIO["Pix"], hovertemplate="%{x}<br>%{y} via Pix<extra></extra>")
        fig.update_layout(barmode="stack")
        mostrar_grafico(layout_grafico(fig, "Boletos processados por dia"))
    with g2:
        fig = go.Figure(go.Bar(x=t["data_fmt"], y=t["liquido_cent"] / 100, marker_color="#0B2545",
                               hovertemplate="%{x}<br>R$ %{y:,.2f}<extra></extra>"))
        mostrar_grafico(layout_grafico(fig, "Entrada líquida de boletos por dia"))

    # ------------------------------------------------------- boletos individuais
    st.subheader("Boletos individuais")
    datas = sorted(b["data_entrada"].unique(), reverse=True)
    escolha = st.selectbox("Data de processamento", datas, format_func=formatar_data, key="bp_dia")
    ind = _por_boleto(b[b["data_entrada"] == escolha])
    st.caption("Datas de criação, pagamento e liquidação vêm da planilha e são exibidas separadamente. "
               "\"Linhas\" indica quantas linhas de split compõem o boleto.")
    st.dataframe(tabela_formatada(ind, NOMES_BOLETO, moedas=MOEDAS, datas=DATAS_BOLETO), hide_index=True)

    # ------------------------------------------------------------ consulta por lote
    st.subheader("Consultar lote")
    lotes = sorted(b["id_lote"].dropna().astype(str).unique())
    lote = st.selectbox("ID do Lote", lotes, key="bp_lote")
    todos_do_lote = df_total[df_total["id_lote"] == lote]
    rl = resumo(todos_do_lote)
    st.caption(f"O lote tem {inteiro(rl['pagamentos'])} pagamento(s) no total (todos os meios), somando "
               f"{formatar_brl(rl['bruto_cent'])} bruto e {formatar_brl(rl['liquido_cent'])} líquido. "
               f"Status: {', '.join(sorted(todos_do_lote['status_lote'].dropna().astype(str).unique()))}. "
               "Abaixo, apenas os boletos do lote.")
    st.dataframe(tabela_formatada(_por_boleto(b[b["id_lote"] == lote]), NOMES_BOLETO, moedas=MOEDAS,
                                  datas=DATAS_BOLETO), hide_index=True)
