"""Dashboard principal."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.formatos import formatar_brl, formatar_data
from core.indicadores import MEIOS, resumo, resumo_por, totais_por_dia

from .comum import (CORES_MEIO, CORES_VALOR, ORDEM_RECEITAS, aviso_sem_dados, bloco_meio, card, cor_receita,
                    dados_filtrados, inteiro, layout_grafico, mostrar_grafico, tabela_formatada, texto_periodo)

HOVER_RS = "%{x}<br>R$ %{y:,.2f}<extra></extra>"


def pagina(con):
    df_total, df, f = dados_filtrados(con)
    st.title("Dashboard")
    if aviso_sem_dados(df_total):
        return
    ativos = f.ativos() - (1 if f.entrada_ini else 0) - (1 if f.entrada_fim else 0)
    st.caption(f"Período: **{texto_periodo(f, df_total)}** · data de entrada das receitas"
               + (f" · {ativos} filtro(s) adicional(is) ativo(s)" if ativos > 0 else ""))
    if df.empty:
        st.warning("Nenhum registro atende aos filtros selecionados.")
        return

    r = resumo(df)
    dias = df["data_entrada"].nunique()
    c = st.columns(5)
    with c[0]: card("Data de entrada", texto_periodo(f, df_total), f"{dias} dia(s) com receita")
    with c[1]: card("Pagamentos", inteiro(r["pagamentos"]), f"{inteiro(r['registros'])} linhas na planilha")
    with c[2]: card("Valor bruto", formatar_brl(r["bruto_cent"]))
    with c[3]: card("Custo financeiro", formatar_brl(r["custo_cent"]), "intermediadora")
    with c[4]: card("Valor líquido", formatar_brl(r["liquido_cent"]))

    # ---------------------------------------------------------------- por meio
    st.subheader("Por meio de pagamento")
    por_meio = resumo_por(df, "meio").set_index("meio")
    vazio = {"pagamentos": 0, "registros": 0, "bruto_cent": 0, "custo_cent": 0, "liquido_cent": 0}
    cols = st.columns(3)
    notas = {"Boleto": "Inclui boleto híbrido quitado via Pix."}
    for col, meio in zip(cols, MEIOS):
        with col:
            dados = por_meio.loc[meio].to_dict() if meio in por_meio.index else vazio
            bloco_meio(meio, dados, notas.get(meio, ""))
    outros = [m for m in por_meio.index if m not in MEIOS]
    if outros:
        st.warning(f"Registros com meio de pagamento não reconhecido: {', '.join(outros)}. "
                   "Eles estão nos totais gerais, mas não em Pix/Cartão/Boleto.")

    # ------------------------------------------------------------- por receita
    st.subheader("Por receita")
    por_rec = resumo_por(df, "receita")
    ordem = {n: i for i, n in enumerate(ORDEM_RECEITAS)}
    por_rec["_o"] = por_rec["receita"].map(lambda x: ordem.get(x, 99))
    por_rec = por_rec.sort_values(["_o", "receita"]).drop(columns="_o")
    total_b = por_rec["bruto_cent"].sum()
    por_rec["part"] = (por_rec["bruto_cent"] / total_b * 100).map(lambda v: f"{v:.1f}%".replace(".", ",")) \
        if total_b else "—"
    st.dataframe(
        tabela_formatada(por_rec, {"receita": "Receita", "pagamentos": "Pagamentos", "bruto_cent": "Valor bruto",
                                   "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido",
                                   "part": "% do bruto"},
                         moedas=("bruto_cent", "custo_cent", "liquido_cent"), inteiros=("pagamentos",)),
        hide_index=True)

    # ----------------------------------------------------------------- gráficos
    diario = totais_por_dia(df)
    diario["data_fmt"] = diario["data_entrada"].map(formatar_data)
    modo = "lines+markers" if len(diario) > 1 else "markers"

    g1, g2 = st.columns(2)
    with g1:
        fig = go.Figure(go.Scatter(x=diario["data_fmt"], y=diario["bruto_cent"] / 100, mode=modo,
                                   line=dict(color=CORES_VALOR["Valor bruto"], width=2), marker=dict(size=8),
                                   hovertemplate=HOVER_RS, name="Valor bruto"))
        mostrar_grafico(layout_grafico(fig, "Evolução diária do valor bruto"))
    with g2:
        fig = go.Figure(go.Scatter(x=diario["data_fmt"], y=diario["liquido_cent"] / 100, mode=modo,
                                   line=dict(color=CORES_VALOR["Valor líquido"], width=2), marker=dict(size=8),
                                   hovertemplate=HOVER_RS, name="Valor líquido"))
        mostrar_grafico(layout_grafico(fig, "Evolução diária do valor líquido"))

    g3, g4 = st.columns(2)
    with g3:
        fig = go.Figure(go.Bar(x=diario["data_fmt"], y=diario["pagamentos"], marker_color="#2a78d6",
                               hovertemplate="%{x}<br>%{y:,} pagamentos<extra></extra>"))
        mostrar_grafico(layout_grafico(fig, "Quantidade de pagamentos por dia"))
    with g4:
        pm = por_meio.reindex([m for m in MEIOS if m in por_meio.index]).reset_index()
        fig = go.Figure(go.Bar(
            y=pm["meio"], x=pm["pagamentos"], orientation="h",
            marker_color=[CORES_MEIO[m] for m in pm["meio"]],
            text=[f"{inteiro(p)} · {formatar_brl(b)}" for p, b in zip(pm["pagamentos"], pm["bruto_cent"])],
            textposition="auto",
            hovertemplate="%{y}<br>%{x:,} pagamentos<extra></extra>"))
        fig.update_yaxes(autorange="reversed")
        mostrar_grafico(layout_grafico(fig, "Distribuição dos pagamentos por meio"))

    g5, g6 = st.columns(2)
    with g5:
        pr = por_rec.sort_values("bruto_cent")
        part = pr["bruto_cent"] / total_b * 100 if total_b else pr["bruto_cent"] * 0
        fig = go.Figure(go.Bar(
            y=pr["receita"], x=part, orientation="h", marker_color=[cor_receita(x) for x in pr["receita"]],
            text=[f"{v:.1f}%".replace(".", ",") for v in part], textposition="auto",
            customdata=[formatar_brl(b) for b in pr["bruto_cent"]],
            hovertemplate="%{y}<br>%{x:.1f}% do bruto<br>%{customdata}<extra></extra>"))
        fig.update_xaxes(ticksuffix="%")
        mostrar_grafico(layout_grafico(fig, "Participação de cada receita (valor bruto)"))
    with g6:
        fig = go.Figure()
        for nome, col in (("Valor bruto", "bruto_cent"), ("Valor líquido", "liquido_cent")):
            fig.add_bar(x=por_rec["receita"], y=por_rec[col] / 100, name=nome, marker_color=CORES_VALOR[nome],
                        hovertemplate="%{x}<br>" + nome + ": R$ %{y:,.2f}<extra></extra>")
        fig.update_layout(barmode="group", bargap=0.25, bargroupgap=0.05)
        mostrar_grafico(layout_grafico(fig, "Comparativo: valor bruto × valor líquido por receita"))

    with st.expander("Ver valores diários em tabela"):
        st.dataframe(tabela_formatada(diario, {
            "data_entrada": "Data de entrada", "pagamentos": "Pagamentos", "bruto_cent": "Valor bruto",
            "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido", "qtd_pix": "Pix",
            "qtd_cartao": "Cartão", "qtd_boleto": "Boleto"},
            moedas=("bruto_cent", "custo_cent", "liquido_cent"), datas=("data_entrada",)), hide_index=True)
