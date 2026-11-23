"""Relatórios e exportações."""
from __future__ import annotations

import re

import streamlit as st

from core import relatorios
from core.banco import registrar_auditoria
from core.marca import PREFIXO_ARQUIVOS
from core.indicadores import status_excluidos

from .auth import pode, usuario_atual
from .comum import aviso_sem_dados, colunas_originais, dados_filtrados, descrever_filtros, inteiro, texto_periodo

DESCRICAO = {
    "dados": "Todos os registros filtrados, com todas as colunas originais da planilha e os valores como vieram.",
    "diario": "Totais por dia (com variação) e por dia × receita, com quantidade de Pix, cartões e boletos.",
    "mensal": "Totais por mês, por mês × receita e por mês × meio de pagamento.",
    "receita": "Totais por receita (CENSEC, e-Not Assina...) e por categoria detalhada.",
    "meio": "Totais por meio (Pix, Cartão, Boleto) e pela forma de pagamento original.",
    "boletos": "Boletos por data de processamento e lista individual de boletos.",
    "inconsistencias": "Resumo das verificações da Conciliação e os registros sinalizados.",
}


def _nome_arquivo(titulo: str, periodo: str, ext: str) -> str:
    base = f"{PREFIXO_ARQUIVOS}_{titulo}_{periodo}".lower()
    base = re.sub(r"[^a-z0-9à-ú]+", "_", base).strip("_")
    return f"{base}.{ext}"


def pagina(con):
    df_total, df, f = dados_filtrados(con)
    st.title("Relatórios")
    if aviso_sem_dados(df_total):
        return
    periodo = texto_periodo(f, df_total)
    filtros = descrever_filtros(f, status_excluidos(con))
    st.caption(f"Período: **{periodo}** · Filtros: {filtros} · {inteiro(len(df))} registro(s). "
               "Os relatórios usam os filtros da barra lateral.")
    if df.empty:
        st.warning("Nenhum registro atende aos filtros selecionados.")
        return

    tipo = st.radio("Relatório", list(relatorios.TIPOS), format_func=relatorios.TIPOS.get, horizontal=True,
                    key="rl_tipo")
    st.caption(DESCRICAO[tipo])
    rel = relatorios.montar(con, tipo, df, periodo, filtros, colunas_originais(con))

    usuario = usuario_atual()
    if not pode("exportar"):
        st.info("Seu perfil não tem permissão para exportar relatórios.")
        return
    c1, c2 = st.columns(2)
    with c1:
        st.download_button("⬇️ Baixar Excel (.xlsx)", data=relatorios.gerar_excel(rel),
                           file_name=_nome_arquivo(rel.titulo, periodo, "xlsx"),
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           type="primary", width="stretch",
                           on_click=lambda: registrar_auditoria(con, usuario, "exportacao_excel",
                                                                f"{rel.titulo} · {periodo} · {filtros}"))
    with c2:
        indice = 0
        if len(rel.tabelas) > 1:
            indice = st.selectbox("Tabela para o CSV", list(range(len(rel.tabelas))),
                                  format_func=lambda i: rel.tabelas[i].nome, key="rl_csv")
        st.download_button("⬇️ Baixar CSV", data=relatorios.gerar_csv(rel, indice),
                           file_name=_nome_arquivo(f"{rel.titulo} {rel.tabelas[indice].nome}", periodo, "csv"),
                           mime="text/csv", width="stretch",
                           on_click=lambda: registrar_auditoria(con, usuario, "exportacao_csv",
                                                                f"{rel.titulo} · {periodo} · {filtros}"))

    st.subheader("Prévia")
    for t in rel.tabelas:
        st.markdown(f"**{t.nome}**")
        prev = t.dados.head(300).copy()
        for c in t.moedas:
            if c in prev:
                prev[c] = prev[c].map(lambda v: "" if v is None or v != v else
                                      f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
        for c in t.datas:
            if c in prev:
                prev[c] = prev[c].map(lambda v: f"{v[8:10]}/{v[5:7]}/{v[:4]}"
                                      if isinstance(v, str) and len(v) >= 10 and v[4] == "-" else v)
        st.dataframe(prev.astype(str).replace({"nan": "", "None": ""}), hide_index=True)
        if len(t.dados) > 300:
            st.caption(f"Prévia com 300 de {inteiro(len(t.dados))} linhas — o arquivo exportado tem todas.")
