"""Conciliação: conferência dos dados, sem alterar valores originais."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from core.conciliacao import (DECISOES, conferencia_composicao, conflitos_pendentes, diferencas_conflito,
                              executar_verificacoes, resolver_conflito)
from core.formatos import formatar_brl
from core.indicadores import aplicar_filtros, aplicar_regra_inclusao, status_excluidos

from .auth import pode, usuario_atual
from .comum import (aviso_sem_dados, card, dados_todos, filtros_sidebar, inteiro,
                    tabela_formatada, texto_periodo)

ICONE = {"erro": "🔴 Erro", "atencao": "🟠 Atenção", "info": "🔵 Informativo"}
MOEDAS = ("valor_bruto_cent", "custo_financeiro_cent", "valor_liquido_cent", "diferenca_cent")
COLUNAS = {"data_entrada": "Data de entrada", "id_parcela": "ID Parcela", "id_venda": "ID da Venda",
           "nr_pedido": "Nº do Pedido", "receita": "Receita", "categoria": "Categoria",
           "sistemas_planilha": "Sistemas (planilha)", "meio": "Meio", "forma_pagamento": "Forma",
           "status_lote": "Status do lote", "id_lote": "ID do Lote", "data_criacao": "Data de criação",
           "data_pagamento": "Data de pagamento", "data_liquidacao": "Data de liquidação",
           "valor_bruto_cent": "Valor bruto", "custo_financeiro_cent": "Custo financeiro",
           "valor_liquido_cent": "Valor líquido", "diferenca_cent": "Diferença", "motivo": "Detalhe",
           "linha_planilha": "Linha no Excel"}
DATAS = ("data_entrada", "data_criacao", "data_pagamento", "data_liquidacao")


def pagina(con):
    todos = dados_todos(con)
    f = filtros_sidebar(todos)
    st.title("Conciliação")
    if aviso_sem_dados(todos):
        return
    df = aplicar_filtros(todos, f)
    st.caption(f"Período: **{texto_periodo(f, todos)}** · as verificações apenas sinalizam; "
               "nenhum valor importado é alterado.")

    verif = executar_verificacoes(con, df)
    n = {g: sum(v.quantidade for v in verif if v.gravidade == g) for g in ICONE}
    pend = conflitos_pendentes(con)
    c = st.columns(4)
    with c[0]: card("🔴 Erros", inteiro(n["erro"]), "valores divergentes ou ausentes")
    with c[1]: card("🟠 Pontos de atenção", inteiro(n["atencao"]), "revisar")
    with c[2]: card("🔵 Informativos", inteiro(n["info"]), "particularidades da planilha")
    with c[3]: card("Conflitos de importação", inteiro(len(pend)), "aguardando sua decisão")

    st.subheader("Verificações")
    st.dataframe(pd.DataFrame([{"Situação": "✅ OK" if v.quantidade == 0 else ICONE[v.gravidade],
                                "Verificação": v.titulo, "Registros": v.quantidade, "O que verifica": v.descricao}
                               for v in verif]), hide_index=True)

    com_registros = [v for v in verif if v.quantidade]
    if com_registros:
        i = st.selectbox("Ver registros da verificação", list(range(len(com_registros))),
                         format_func=lambda k: f"{com_registros[k].titulo} ({com_registros[k].quantidade})",
                         key="cc_verif")
        escolha = com_registros[i]
        reg = escolha.registros
        st.caption(escolha.descricao)
        st.dataframe(tabela_formatada(reg, COLUNAS, moedas=MOEDAS, datas=DATAS), hide_index=True)

    # ------------------------------------------------------------ composição
    st.subheader("Conferência da composição dos valores")
    st.caption("Confere se os totais do Dashboard fecham com a soma das partes (por meio, receita e dia).")
    ind = aplicar_regra_inclusao(df, status_excluidos(con))
    comp = conferencia_composicao(ind)
    comp["Total geral"] = [formatar_brl(t) if u == "R$" else inteiro(t) for t, u in zip(comp["total"], comp["unidade"])]
    comp["Soma das partes"] = [formatar_brl(t) if u == "R$" else inteiro(t)
                               for t, u in zip(comp["partes"], comp["unidade"])]
    comp["Confere"] = comp["Confere"].map({True: "✅ Sim", False: "🔴 Não"})
    st.dataframe(comp[["Composição", "Medida", "Total geral", "Soma das partes", "Confere"]], hide_index=True)
    excl = status_excluidos(con)
    if excl:
        fora = len(df) - len(ind)
        st.info(f"{inteiro(fora)} registro(s) com status {', '.join(excl)} estão fora dos indicadores "
                "(regra definida em Configurações), mas aparecem nas verificações acima.")

    # ------------------------------------------------------------- conflitos
    st.subheader("Conflitos de importação")
    if pend.empty:
        st.success("Nenhum conflito pendente.")
        return
    st.caption("Registro que chegou com o mesmo identificador (ID da Venda) de um registro já gravado, "
               "mas com conteúdo diferente. O registro atual foi mantido até a sua decisão.")
    usuario = usuario_atual()
    for _, cf in pend.iterrows():
        with st.expander(f"Conflito nº {cf['id']} — {cf['chave_registro']} · arquivo {cf['arquivo']} "
                         f"(linha {cf['linha_planilha']})"):
            if not isinstance(cf["dados_atuais"], str):
                st.warning("O registro atual com este identificador foi removido (importação excluída). "
                           "\"Substituir\" ou \"Manter os dois\" gravam o registro novo; "
                           "\"Manter o registro atual\" descarta o novo.")
            st.dataframe(diferencas_conflito(cf["dados_atuais"], cf["dados_novos"]).astype(str), hide_index=True)
            if not pode("resolver_conflito"):
                st.caption("A decisão sobre conflitos é feita pelo administrador ou pelos operadores.")
                continue
            decisao = st.radio("Decisão", list(DECISOES), format_func=DECISOES.get, key=f"cf_dec_{cf['id']}")
            if st.button("Confirmar decisão", key=f"cf_ok_{cf['id']}", type="primary"):
                resolver_conflito(con, int(cf["id"]), decisao, usuario)
                st.success("Decisão registrada.")
                st.rerun()
