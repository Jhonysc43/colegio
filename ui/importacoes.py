"""Importações: prévia, validação, confirmação e histórico."""
from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

from core.formatos import formatar_brl, formatar_data
from core.importacao import (ErroImportacao, analisar_arquivo, arquivo_ja_importado, confirmar_importacao,
                             excluir_importacao, listar_abas, previa_exclusao)

from .auth import pode, usuario_atual
from .comum import card

ROTULOS_ALERTA = {
    "data_formato_corrigido": "Data fora do padrão (interpretada)",
    "data_invalida": "Data inválida",
    "data_inconsistente": "Datas inconsistentes",
    "divergencia_liquido": "Líquido ≠ Bruto − Custo",
    "valor_invalido": "Valor não numérico",
    "valor_vazio": "Valor vazio",
    "valor_negativo": "Valor negativo",
    "status_diferente": "Status do lote diferente de 'Pago'",
    "duplicada_no_arquivo": "Registro repetido no próprio arquivo",
}


def pagina(con):
    st.title("Importações")
    if not pode("importar"):
        st.error("Seu perfil não tem permissão para importar planilhas.")
        return
    st.caption("Importe a planilha da intermediadora. Nada é gravado antes da sua confirmação.")

    arquivo = st.file_uploader("Planilha Excel (.xlsx)", type=["xlsx", "xlsm", "xls"])
    if not arquivo:
        historico(con)
        return

    tmpdir = Path(tempfile.mkdtemp())
    caminho = tmpdir / arquivo.name
    caminho.write_bytes(arquivo.getvalue())  # cópia temporária; o arquivo de origem não é alterado

    try:
        abas = listar_abas(caminho)
    except ErroImportacao as e:
        st.error(str(e))
        return
    aba = st.selectbox("Aba", abas) if len(abas) > 1 else abas[0]

    try:
        with st.spinner("Lendo e validando a planilha..."):
            a = analisar_arquivo(caminho, aba=aba, nome_original=arquivo.name)
    except ErroImportacao as e:
        st.error(str(e))
        return

    t = a.totais()
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1: card("Registros (linhas)", f"{t['registros']:,}".replace(",", "."))
    with c2: card("Pagamentos (ID Parcela)", f"{t['pagamentos (ID Parcela distintos)']:,}".replace(",", "."))
    with c3: card("Valor bruto", formatar_brl(t["bruto_cent"]))
    with c4: card("Custo financeiro", formatar_brl(t["custo_cent"]))
    with c5: card("Valor líquido", formatar_brl(t["liquido_cent"]))

    st.write(f"Cabeçalho encontrado na linha **{a.linha_cabecalho}** · **{len(a.colunas)} colunas** identificadas · "
             f"**{len(a.linhas_ignoradas)}** linhas de resumo/sem identificador não serão importadas.")

    anteriores = arquivo_ja_importado(con, a.hash_arquivo)
    if anteriores:
        st.warning(f"Este mesmo arquivo já foi importado {len(anteriores)} vez(es) "
                   f"(última em {anteriores[-1]['processado_em'][:16].replace('T', ' ')}). "
                   "Registros já existentes não serão duplicados.")

    if a.alertas:
        st.subheader("Inconsistências encontradas")
        linhas = [{"Tipo": ROTULOS_ALERTA.get(tp, tp), "Coluna": col or "—", "Linhas afetadas": qtd,
                   "Exemplos (linha do Excel)": ", ".join(map(str, ex[:10]))}
                  for tp, col, qtd, ex in a.alertas_agrupados()]
        st.dataframe(pd.DataFrame(linhas), hide_index=True)
    else:
        st.success("Nenhuma inconsistência encontrada.")

    if a.linhas_ignoradas:
        with st.expander(f"Linhas que não serão importadas ({len(a.linhas_ignoradas)})"):
            st.dataframe(pd.DataFrame([{"Linha": n, "Motivo": m, "Conteúdo": " | ".join(map(str, c))}
                                       for n, m, c in a.linhas_ignoradas]), hide_index=True)

    st.subheader("Prévia dos dados")
    prev = pd.DataFrame([l.dados for l in a.linhas[:500]], columns=a.colunas)
    padrao = [c for c in ["ID Parcela", "Nº do Pedido", "Forma de Pagamento", "Meio de Pagamento", "Valor Bruto",
                          "Custo Financeiro", "Valor Líquido", "Data de Pagamento", "Sistemas"] if c in a.colunas]
    visiveis = st.multiselect("Colunas exibidas", a.colunas, default=padrao)
    st.dataframe(prev[visiveis or a.colunas], hide_index=True)
    if len(a.linhas) > 500:
        st.caption(f"Mostrando 500 de {len(a.linhas)} registros.")

    st.subheader("Confirmar importação")
    sugerida = date.fromisoformat(a.data_liquidacao_sugerida) if a.data_liquidacao_sugerida else date.today()
    data_entrada = st.date_input("Data de entrada das receitas", value=sugerida, format="DD/MM/YYYY",
                                 help="Data usada como referência nos indicadores. "
                                      "Sugestão: data de liquidação encontrada na planilha.")
    if a.data_liquidacao_sugerida and data_entrada.isoformat() != a.data_liquidacao_sugerida:
        st.info(f"A data informada é diferente da data de liquidação da planilha "
                f"({formatar_data(a.data_liquidacao_sugerida)}).")

    tratamento = "manter_uma"
    if a.duplicadas_no_arquivo:
        escolha = st.radio(
            f"{len(a.duplicadas_no_arquivo)} registro(s) aparecem repetidos neste arquivo. Como tratar?",
            ["Importar apenas a primeira ocorrência", "Importar todas as ocorrências"])
        tratamento = "manter_uma" if escolha.startswith("Importar apenas") else "manter_todas"

    usuario = usuario_atual()
    if st.button("Confirmar importação", type="primary") and pode("importar"):
        r = confirmar_importacao(con, a, data_entrada.isoformat(), usuario, duplicadas=tratamento)
        st.success(f"Importação nº {r.importacao_id} concluída: {r.inseridas} registros novos, "
                   f"{r.ja_existentes} já existentes (não duplicados), {r.conflitos} conflitos para revisão.")
        if r.conflitos:
            st.warning("Há registros com o mesmo identificador e conteúdo diferente do já gravado. "
                       "O original foi mantido; os conflitos ficam disponíveis para sua decisão.")

    historico(con)


def historico(con):
    st.subheader("Histórico de importações")
    linhas = con.execute(
        "SELECT id, arquivo, aba, data_entrada, processado_em, usuario, linhas_lidas, linhas_inseridas,"
        " linhas_ja_existentes, linhas_conflito, linhas_ignoradas, alertas, resultado, excluida_em, excluida_por"
        " FROM importacoes ORDER BY id DESC").fetchall()
    if not linhas:
        st.caption("Nenhuma importação realizada ainda.")
        return
    df = pd.DataFrame([dict(l) for l in linhas])
    df["data_entrada"] = df["data_entrada"].map(formatar_data)
    df["processado_em"] = pd.to_datetime(df["processado_em"]).dt.strftime("%d/%m/%Y %H:%M")
    df["resultado"] = df["resultado"].map({"concluida": "Concluída",
                                           "concluida_com_alertas": "Concluída com alertas"})
    # pd.notna: no pandas 3, campo vazio vira NaN (que não é "falso" em Python)
    df["situacao"] = [f"🗑️ Excluída em {pd.to_datetime(e):%d/%m/%Y %H:%M} por {u if pd.notna(u) else '—'}"
                      if pd.notna(e) else "Ativa"
                      for e, u in zip(df["excluida_em"], df["excluida_por"])]
    df = df[["id", "situacao", "arquivo", "aba", "data_entrada", "processado_em", "usuario", "linhas_lidas",
             "linhas_inseridas", "linhas_ja_existentes", "linhas_conflito", "linhas_ignoradas", "alertas",
             "resultado"]]
    df.columns = ["Nº", "Situação", "Arquivo", "Aba", "Data de entrada", "Processado em", "Usuário", "Lidas",
                  "Novas", "Já existentes", "Conflitos", "Ignoradas", "Alertas", "Resultado"]
    st.dataframe(df, hide_index=True)
    if pode("excluir_importacao"):
        excluir(con)


def excluir(con):
    ativas = con.execute("SELECT id, arquivo, data_entrada, processado_em FROM importacoes"
                         " WHERE excluida_em IS NULL ORDER BY id DESC").fetchall()
    with st.expander("🗑️ Excluir uma importação feita por engano"):
        if not ativas:
            st.caption("Nenhuma importação ativa.")
            return
        rotulos = {r["id"]: f"Nº {r['id']} — {r['arquivo']} · entrada {formatar_data(r['data_entrada'])} · "
                            f"importada em {pd.to_datetime(r['processado_em']):%d/%m/%Y %H:%M}" for r in ativas}
        imp_id = st.selectbox("Importação", list(rotulos), format_func=rotulos.get, index=None,
                              placeholder="Escolha a importação...", key="exc_imp")
        if imp_id is None:
            return
        p = previa_exclusao(con, imp_id)
        st.markdown("**Será removido:**")
        c = st.columns(4)
        with c[0]: card("Registros", f"{p.registros:,}".replace(",", "."), f"{p.pagamentos} pagamento(s)")
        with c[1]: card("Valor bruto", formatar_brl(p.bruto_cent))
        with c[2]: card("Custo financeiro", formatar_brl(p.custo_cent))
        with c[3]: card("Valor líquido", formatar_brl(p.liquido_cent))
        if p.ja_existentes:
            st.info(f"{p.ja_existentes} registro(s) desta planilha já existiam por importações anteriores e "
                    "**não** serão removidos.")
        if p.registros == 0 and not p.bloqueios:
            st.info("Esta importação não trouxe registros novos. Excluir apenas a marcará como excluída no histórico.")
        if p.classificacoes_manuais:
            st.warning(f"{len(p.classificacoes_manuais)} pagamento(s) desta importação têm classificação manual "
                       f"(ID Parcela {', '.join(p.classificacoes_manuais[:10])}"
                       f"{'...' if len(p.classificacoes_manuais) > 10 else ''}). A classificação fica guardada e "
                       "volta a valer se você importar a planilha correta.")
        if p.conflitos_pendentes:
            st.warning(f"{p.conflitos_pendentes} conflito(s) pendente(s) desta importação serão descartados.")
        if p.bloqueios:
            for b in p.bloqueios:
                st.error(b)
            return
        st.caption("Um backup completo será feito automaticamente antes da exclusão. "
                   "A importação continuará no histórico, marcada como excluída.")
        ok = st.checkbox("Confirmo que quero excluir esta importação.", key=f"exc_ok_{imp_id}")
        st.button("Excluir importação", type="primary", disabled=not ok, key=f"exc_btn_{imp_id}",
                  on_click=_executar_exclusao, args=(con, imp_id))
    if st.session_state.get("exc_msg"):
        st.success(st.session_state.pop("exc_msg"))
    if st.session_state.get("exc_erro"):
        st.error(st.session_state.pop("exc_erro"))


def _executar_exclusao(con, imp_id: int):
    """Executado ao clicar no botão (antes de a tela ser redesenhada)."""
    usuario = usuario_atual()
    if not pode("excluir_importacao"):
        st.session_state["exc_erro"] = "Somente o administrador pode excluir importações."
        return
    try:
        p = excluir_importacao(con, imp_id, usuario)
    except ValueError as e:
        st.session_state["exc_erro"] = str(e)
        return
    st.session_state["exc_msg"] = (f"Importação nº {imp_id} excluída: {p.registros} registro(s) removido(s). "
                                   "Um backup foi salvo antes da exclusão.")
    st.session_state.pop("exc_imp", None)
