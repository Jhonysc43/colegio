"""Elementos compartilhados da interface: estilo, cards, formatação, cores, filtros."""
from __future__ import annotations

import json
from datetime import date

import pandas as pd
import streamlit as st

from core.formatos import formatar_brl, formatar_data
from core.indicadores import (MEIOS, Filtros, aplicar_filtros, aplicar_regra_inclusao, carregar_dataframe,
                              status_excluidos)

AZUL_MARINHO = "#0B2545"

# Paleta categórica validada (daltonismo e separação) — cada entidade tem cor fixa,
# que não muda quando um filtro remove outras séries.
CORES_MEIO = {"Pix": "#2a78d6", "Cartão": "#eb6834", "Boleto": "#1baf7a"}
ORDEM_RECEITAS = ["CENSEC", "Fatura quinzenal tabelião", "e-Not Assina", "e-Not Certidões/AEV",
                  "e-Not Provas", "BuscaCEP", "Desmaterialização e-Not Auto"]
_SLOTS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6"]
CINZA = "#8a8f98"
CORES_VALOR = {"Valor bruto": "#2a78d6", "Valor líquido": "#1baf7a"}


def cor_receita(nome: str) -> str:
    if nome in ORDEM_RECEITAS:
        return _SLOTS[ORDEM_RECEITAS.index(nome)]
    return CINZA


def aplicar_estilo():
    st.markdown(
        f"""
        <style>
          .stApp {{ background-color: #F6F8FB; }}
          [data-testid="stSidebar"] {{ background-color: {AZUL_MARINHO}; }}
          [data-testid="stSidebar"] p, [data-testid="stSidebar"] label, [data-testid="stSidebar"] span,
          [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ color: #FFFFFF; }}
          [data-testid="stSidebar"] input, [data-testid="stSidebar"] [data-baseweb="select"] span {{ color: #1F2937; }}
          .cf-card {{ background:#FFFFFF; border:1px solid #E3E8EF; border-radius:10px; padding:12px 16px;
                      height:100%; }}
          .cf-card .rot {{ color:#5B6B7F; font-size:0.82rem; margin-bottom:2px; }}
          .cf-card .val {{ color:{AZUL_MARINHO}; font-size:1.3rem; font-weight:600; line-height:1.3; }}
          .cf-card .sub {{ color:#5B6B7F; font-size:0.78rem; }}
          .cf-meio {{ background:#FFFFFF; border:1px solid #E3E8EF; border-radius:10px; padding:12px 16px; }}
          .cf-meio h4 {{ margin:0 0 6px 0; color:{AZUL_MARINHO}; font-size:1rem; }}
          .cf-meio .lin {{ display:flex; justify-content:space-between; font-size:0.9rem; padding:2px 0;
                           color:#1F2937; }}
          .cf-meio .lin span:first-child {{ color:#5B6B7F; }}
          .cf-tag {{ display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def card(rotulo: str, valor: str, sub: str = ""):
    st.markdown(f'<div class="cf-card"><div class="rot">{rotulo}</div><div class="val">{valor}</div>'
                f'<div class="sub">{sub}</div></div>', unsafe_allow_html=True)


def bloco_meio(nome: str, r: dict, nota: str = ""):
    linhas = [("Pagamentos", inteiro(r["pagamentos"])), ("Valor bruto", formatar_brl(r["bruto_cent"])),
              ("Custo financeiro", formatar_brl(r["custo_cent"])), ("Valor líquido", formatar_brl(r["liquido_cent"]))]
    html = "".join(f'<div class="lin"><span>{a}</span><span>{b}</span></div>' for a, b in linhas)
    nota_html = f'<div class="sub" style="color:#5B6B7F;font-size:0.75rem;margin-top:4px">{nota}</div>' if nota else ""
    st.markdown(f'<div class="cf-meio"><h4><span class="cf-tag" style="background:{CORES_MEIO.get(nome, CINZA)}">'
                f'</span>{nome}</h4>{html}{nota_html}</div>', unsafe_allow_html=True)


def inteiro(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def pct(v) -> str:
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%".replace(".", ",")


def tabela_formatada(df: pd.DataFrame, renomear: dict, moedas=(), datas=(), inteiros=()) -> pd.DataFrame:
    """Converte para exibição em PT-BR (R$ 1.234,56 e DD/MM/AAAA) sem alterar o df de origem."""
    out = df.copy()
    for c in moedas:
        if c in out:
            out[c] = out[c].map(formatar_brl)
    for c in datas:
        if c in out:
            out[c] = out[c].map(formatar_data)
    for c in inteiros:
        if c in out:
            out[c] = out[c].map(inteiro)
    cols = [c for c in renomear if c in out]
    return out[cols].rename(columns=renomear)


def extrair_original(df: pd.DataFrame, colunas: list[str]) -> pd.DataFrame:
    """Lê colunas da planilha original (guardadas em dados_originais)."""
    dados = df["dados_originais"].map(json.loads)
    out = df.copy()
    for c in colunas:
        out[c] = dados.map(lambda d: d.get(c))
    return out


def layout_grafico(fig, titulo: str, altura: int = 320):
    fig.update_layout(
        title=dict(text=titulo, font=dict(size=15, color=AZUL_MARINHO), x=0, xanchor="left"),
        separators=",.",  # 1.234,56
        height=altura, margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
        font=dict(color="#374151", size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, title_text=""),
        hoverlabel=dict(bgcolor="#FFFFFF", font_color="#1F2937"),
    )
    fig.update_xaxes(showgrid=False, linecolor="#D1D5DB", title_text="")
    fig.update_yaxes(gridcolor="#EEF1F5", zeroline=False, title_text="")
    return fig


def mostrar_grafico(fig):
    st.plotly_chart(fig, config={"displayModeBar": False, "locale": "pt-BR"})


# ------------------------------------------------------------------ dados e filtros
def _versao_dados(con) -> str:
    partes = [
        con.execute("SELECT COALESCE(MAX(id),0) FROM importacoes").fetchone()[0],
        con.execute("SELECT COUNT(*), COALESCE(MAX(definida_em),'') FROM classificacoes_manuais").fetchone(),
        con.execute("SELECT COUNT(*), COALESCE(MAX(id),0), COALESCE(SUM(ativa),0) FROM regras_classificacao").fetchone(),
        con.execute("SELECT group_concat(categoria || '=' || grupo) FROM grupos_receita").fetchone()[0],
        con.execute("SELECT COUNT(*), COALESCE(MAX(decidido_em),'') FROM conflitos").fetchone(),
    ]
    return json.dumps(partes, default=list)


@st.cache_data(show_spinner="Carregando dados...")
def _carregar(_con, versao: str) -> pd.DataFrame:
    return carregar_dataframe(_con)


def dados_todos(con) -> pd.DataFrame:
    """Todos os registros, sem a regra de inclusão por status (usado na Conciliação)."""
    return _carregar(con, _versao_dados(con))


def dados_completos(con) -> pd.DataFrame:
    """Registros que entram nos indicadores (aplica a regra de inclusão por status)."""
    return aplicar_regra_inclusao(dados_todos(con), status_excluidos(con))


def colunas_originais(con) -> list[str]:
    """União das colunas originais de todas as importações, na ordem em que apareceram."""
    cols: list[str] = []
    for (c,) in con.execute("SELECT colunas FROM importacoes ORDER BY id"):
        for nome in json.loads(c):
            if nome not in cols:
                cols.append(nome)
    return cols


def descrever_filtros(f: Filtros, excluidos: list[str] | None = None) -> str:
    partes = []
    pares = [("Data de pagamento", f.pagamento_ini, f.pagamento_fim),
             ("Data de liquidação", f.liquidacao_ini, f.liquidacao_fim)]
    for rot, ini, fim in pares:
        if ini or fim:
            partes.append(f"{rot}: {formatar_data(ini)} a {formatar_data(fim)}")
    for rot, vals in (("Receita", f.receitas), ("Meio", f.meios), ("Forma", f.formas), ("Status", f.status),
                      ("Estabelecimento", f.estabelecimentos), ("Sistema", f.sistemas)):
        if vals:
            partes.append(f"{rot}: {', '.join(vals)}")
    for rot, v in (("ID do Lote", f.id_lote), ("ID Parcela", f.id_parcela), ("Nº do Pedido", f.nr_pedido)):
        if v.strip():
            partes.append(f"{rot} contém \"{v.strip()}\"")
    if excluidos:
        partes.append(f"Status fora dos indicadores: {', '.join(excluidos)}")
    return "; ".join(partes) or "nenhum"


def _limpar_filtros():
    for k in list(st.session_state.keys()):
        if k.startswith("f_"):
            del st.session_state[k]


def _intervalo(valor) -> tuple[str | None, str | None]:
    if isinstance(valor, (list, tuple)):
        if len(valor) == 2:
            return valor[0].isoformat(), valor[1].isoformat()
        if len(valor) == 1:
            return valor[0].isoformat(), valor[0].isoformat()
        return None, None
    if isinstance(valor, date):
        return valor.isoformat(), valor.isoformat()
    return None, None


def _opcoes(df: pd.DataFrame, col: str, ordem: list[str] | None = None) -> list[str]:
    if df.empty:
        return []
    vals = sorted(df[col].dropna().astype(str).unique())
    if ordem:
        vals = [v for v in ordem if v in vals] + [v for v in vals if v not in ordem]
    return vals


def filtros_sidebar(df: pd.DataFrame) -> Filtros:
    """Filtros globais: valem para todos os indicadores, tabelas e gráficos da página."""
    f = Filtros()
    with st.sidebar:
        st.markdown("### Filtros")
        if df.empty:
            st.caption("Importe uma planilha para habilitar os filtros.")
            return f
        dmin = date.fromisoformat(df["data_entrada"].min())
        dmax = date.fromisoformat(df["data_entrada"].max())
        per = st.date_input("Período (data de entrada)", value=(dmin, dmax), format="DD/MM/YYYY", key="f_entrada")
        f.entrada_ini, f.entrada_fim = _intervalo(per)

        if st.checkbox("Filtrar por data de pagamento", key="f_usa_pag"):
            per = st.date_input("Data de pagamento", value=(dmin, dmax), format="DD/MM/YYYY", key="f_pag")
            f.pagamento_ini, f.pagamento_fim = _intervalo(per)
        if st.checkbox("Filtrar por data de liquidação", key="f_usa_liq"):
            per = st.date_input("Data de liquidação (planilha)", value=(dmin, dmax), format="DD/MM/YYYY",
                                key="f_liq")
            f.liquidacao_ini, f.liquidacao_fim = _intervalo(per)

        f.receitas = st.multiselect("Receita", _opcoes(df, "receita", ORDEM_RECEITAS), key="f_receita",
                                    placeholder="Todas")
        f.meios = st.multiselect("Meio de pagamento", _opcoes(df, "meio", MEIOS), key="f_meio", placeholder="Todos")
        with st.expander("Mais filtros"):
            f.formas = st.multiselect("Forma de pagamento", _opcoes(df, "forma_pagamento"), key="f_forma",
                                      placeholder="Todas")
            f.status = st.multiselect("Status do lote", _opcoes(df, "status_lote"), key="f_status",
                                      placeholder="Todos")
            f.estabelecimentos = st.multiselect("Estabelecimento", _opcoes(df, "estabelecimento"), key="f_estab",
                                                placeholder="Todos")
            f.sistemas = st.multiselect("Sistema (coluna da planilha)", _opcoes(df, "sistemas_planilha"),
                                        key="f_sist", placeholder="Todos")
            f.id_lote = st.text_input("ID do Lote", key="f_lote")
            f.id_parcela = st.text_input("ID Parcela", key="f_parcela")
            f.nr_pedido = st.text_input("Nº do Pedido", key="f_pedido")
        st.button("Limpar todos os filtros", on_click=_limpar_filtros, width="stretch")
    return f


def dados_filtrados(con) -> tuple[pd.DataFrame, pd.DataFrame, Filtros]:
    df = dados_completos(con)
    f = filtros_sidebar(df)
    return df, aplicar_filtros(df, f), f


def texto_periodo(f: Filtros, df: pd.DataFrame) -> str:
    if df.empty:
        return "—"
    ini = f.entrada_ini or df["data_entrada"].min()
    fim = f.entrada_fim or df["data_entrada"].max()
    return formatar_data(ini) if ini == fim else f"{formatar_data(ini)} a {formatar_data(fim)}"


def aviso_sem_dados(df_total: pd.DataFrame) -> bool:
    if df_total.empty:
        st.info("Nenhum dado importado ainda. Use a tela **Importações** para carregar uma planilha.")
        return True
    return False
