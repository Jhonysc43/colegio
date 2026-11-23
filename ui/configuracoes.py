"""Configurações: regras de classificação, receitas, revisão manual, inclusão, backup e auditoria."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st

from core import banco, classificacao
from core.classificacao import NAO_IDENTIFICADO, OPERADORES
from core.formatos import formatar_brl
from core.indicadores import definir_status_excluidos, status_excluidos

from . import usuarios as usuarios_ui
from .auth import pode, usuario_atual
from .comum import colunas_originais, dados_todos, inteiro

REGRAS_DOCUMENTADAS = [
    ("Receita recebida", "Todos os registros importados contam como receita recebida, exceto os status "
                         "retirados na aba \"Inclusão nos indicadores\"."),
    ("Data de referência", "Data de entrada informada pela usuária em cada importação."),
    ("Quantidade de pagamentos", "Número de ID Parcela distintos. As linhas de split do mesmo pagamento somam "
                                 "nos valores, mas o pagamento conta uma vez."),
    ("Valores", "Soma de todas as linhas. Guardados em centavos, sem arredondamento."),
    ("Validação", "Valor Líquido = Valor Bruto − Custo Financeiro. Divergências são sinalizadas, nunca corrigidas."),
    ("Tarifa", "\"Tarifa parcela Express\" corresponde ao Custo Financeiro."),
    ("Pix / Cartão / Boleto", "Meio \"Boleto Híbrido\" = Boleto, mesmo quitado via Pix. Senão, pela Forma: "
                              "PIX = Pix; Crédito/Débito = Cartão."),
    ("Boletos processados", "Data de processamento = data de entrada."),
    ("Classificação", "Classificação manual (por ID Parcela) > regras ativas por prioridade > \"Não identificado\"."),
    ("Receita CENSEC", "CENSEC = BuscaTestamento (aba Receitas)."),
    ("Duplicidade", "Chave = ID da Venda. Reimportar não duplica; conteúdo diferente vira conflito para decisão."),
    ("Acesso", "Administrador: tudo. Operador: importa, classifica, resolve conflitos e exporta. "
               "Consulta: vê todas as telas de acompanhamento e exporta, sem alterar dados."),
    ("Exclusão de importação", "Remove só os registros que entraram por ela, após backup automático. Fica no "
                               "histórico como excluída; classificações manuais são mantidas."),
]


def pagina(con):
    st.title("Configurações")
    usuario = usuario_atual()
    secoes = [
        ("Usuários", "gerenciar_usuarios", lambda: usuarios_ui.secao(con, usuario)),
        ("Regras de classificação", "editar_regras", lambda: _regras(con, usuario)),
        ("Receitas", "editar_receitas", lambda: _grupos(con, usuario)),
        ("Revisão manual", "classificar_manual", lambda: _revisao(con, usuario)),
        ("Inclusão nos indicadores", "regra_inclusao", lambda: _inclusao(con, usuario)),
        ("Backup", "backup", lambda: _backup(con, usuario)),
        ("Auditoria", "ver_auditoria", lambda: _auditoria(con)),
        ("Regras financeiras", None, _regras_documentadas),
    ]
    visiveis = [(nome, f) for nome, acao, f in secoes if acao is None or pode(acao)]
    for aba, (_, f) in zip(st.tabs([n for n, _ in visiveis]), visiveis):
        with aba:
            f()


def _regras_documentadas():
    st.caption("Regras usadas nos cálculos, confirmadas com a usuária. Também estão no README.md.")
    st.dataframe(pd.DataFrame(REGRAS_DOCUMENTADAS, columns=["Regra", "Definição"]), hide_index=True)


def _regras(con, usuario):
    st.caption("A primeira regra ativa que combinar define a categoria (menor prioridade primeiro). "
               "Classificações manuais sempre prevalecem. As mudanças valem para todos os dados, "
               "inclusive os já importados.")
    atuais = pd.DataFrame([dict(r) for r in con.execute(
        "SELECT campo, operador, valor, categoria, prioridade, ativa FROM regras_classificacao"
        " ORDER BY prioridade, LENGTH(valor) DESC, id")])
    if atuais.empty:
        atuais = pd.DataFrame(columns=["campo", "operador", "valor", "categoria", "prioridade", "ativa"])
    atuais["ativa"] = atuais["ativa"].astype(bool)
    campos = colunas_originais(con) or ["Nº do Pedido", "Descrição", "Sistemas"]
    editado = st.data_editor(
        atuais, num_rows="dynamic", hide_index=True, key="cfg_regras",
        column_config={
            "campo": st.column_config.SelectboxColumn("Coluna da planilha", options=campos, required=True),
            "operador": st.column_config.SelectboxColumn("Condição", options=list(OPERADORES), required=True,
                                                         help="comeca_com = começa com; contem = contém; "
                                                              "igual = é igual a"),
            "valor": st.column_config.TextColumn("Valor", required=True),
            "categoria": st.column_config.TextColumn("Categoria", required=True),
            "prioridade": st.column_config.NumberColumn("Prioridade", min_value=0, step=1, default=50),
            "ativa": st.column_config.CheckboxColumn("Ativa", default=True),
        })
    editado = editado.astype(object).where(pd.notna(editado), None)
    regras = [r for r in editado.to_dict("records") if any(str(v if v is not None else "").strip()
                                                           for k, v in r.items() if k != "ativa")]

    df = dados_todos(con)
    if not df.empty:
        dados = [json.loads(d) for d in df["dados_originais"]]
        manuais = set(r[0] for r in con.execute("SELECT id_parcela FROM classificacoes_manuais"))
        dados_auto = [d for d, p in zip(dados, df["id_parcela"]) if p not in manuais]
        atual = classificacao.simular(atuais.to_dict("records"), dados_auto)
        novo = classificacao.simular(regras, dados_auto)
        comp = pd.DataFrame([{"Categoria": c, "Registros hoje": atual.get(c, 0), "Com as alterações": novo.get(c, 0)}
                             for c in sorted(set(atual) | set(novo))])
        if not comp.empty and (comp["Registros hoje"] != comp["Com as alterações"]).any():
            st.markdown("**Efeito das alterações (antes de salvar)**")
            st.dataframe(comp, hide_index=True)

    erros = classificacao.validar_regras(regras)
    if erros:
        st.error(" ".join(erros))
    if st.button("Salvar regras", type="primary", disabled=bool(erros), key="cfg_salvar_regras"):
        classificacao.salvar_regras(con, regras, usuario)
        st.success("Regras salvas.")
        st.rerun()


def _grupos(con, usuario):
    st.caption("Agrupa categorias em receitas para o Dashboard e os relatórios. "
               "Categoria sem grupo aparece com o próprio nome.")
    grupos = pd.DataFrame(list(classificacao.carregar_grupos(con).items()), columns=["categoria", "grupo"])
    cats = sorted({r[0] for r in con.execute("SELECT categoria FROM regras_classificacao")}
                  | {r[0] for r in con.execute("SELECT categoria FROM classificacoes_manuais")})
    editado = st.data_editor(grupos, num_rows="dynamic", hide_index=True, key="cfg_grupos", column_config={
        "categoria": st.column_config.SelectboxColumn("Categoria", options=cats, required=True),
        "grupo": st.column_config.TextColumn("Receita (grupo)", required=True)})
    if st.button("Salvar receitas", type="primary", key="cfg_salvar_grupos"):
        editado = editado.astype(object).where(pd.notna(editado), None)
        novos = {r["categoria"]: r["grupo"] for r in editado.to_dict("records") if r.get("categoria") and r.get("grupo")}
        classificacao.salvar_grupos(con, novos, usuario)
        st.success("Receitas salvas.")
        st.rerun()


def _revisao(con, usuario):
    df = dados_todos(con)
    st.markdown("**Registros não identificados**")
    nao = df[df["categoria"] == NAO_IDENTIFICADO] if not df.empty else df
    cats = sorted({r[0] for r in con.execute("SELECT categoria FROM regras_classificacao")})
    if nao.empty:
        st.success("Nenhum registro sem classificação.")
    else:
        agg = nao.groupby("id_parcela").agg(pedido=("nr_pedido", "first"), entrada=("data_entrada", "max"),
                                            bruto=("valor_bruto_cent", "sum"), linhas=("id", "size")).reset_index()
        st.dataframe(pd.DataFrame({"ID Parcela": agg["id_parcela"], "Nº do Pedido": agg["pedido"],
                                   "Valor bruto": agg["bruto"].map(formatar_brl), "Linhas": agg["linhas"]}),
                     hide_index=True)
    st.markdown("**Classificar manualmente**")
    st.caption("Vale para todas as linhas do pagamento (ID Parcela) e é mantida nas próximas importações.")
    with st.form("cfg_form_manual", clear_on_submit=True):
        opcoes = list(nao["id_parcela"].unique()) if not nao.empty else []
        c1, c2 = st.columns(2)
        parcela = c1.selectbox("ID Parcela (não identificados)", opcoes, index=None,
                               placeholder="Escolha..." if opcoes else "Nenhum pendente")
        outra = c2.text_input("…ou digite outro ID Parcela")
        c3, c4 = st.columns(2)
        cat = c3.selectbox("Categoria", cats, index=None, placeholder="Escolha...")
        nova = c4.text_input("…ou nova categoria")
        motivo = st.text_input("Motivo (obrigatório)")
        if st.form_submit_button("Salvar classificação", type="primary"):
            pid = (outra or parcela or "").strip()
            categoria = (nova or cat or "").strip()
            if not pid or not categoria or not motivo.strip():
                st.error("Informe o ID Parcela, a categoria e o motivo.")
            elif df.empty or pid not in set(df["id_parcela"]):
                st.error(f"ID Parcela {pid} não encontrado nos dados importados.")
            else:
                classificacao.definir_manual(con, pid, categoria, usuario, motivo.strip())
                st.success(f"ID Parcela {pid} classificado como {categoria}.")
                st.rerun()

    manuais = pd.DataFrame([dict(r) for r in con.execute(
        "SELECT id_parcela, categoria, motivo, usuario, definida_em FROM classificacoes_manuais ORDER BY definida_em DESC")])
    st.markdown("**Classificações manuais em vigor**")
    if manuais.empty:
        st.caption("Nenhuma.")
        return
    manuais["definida_em"] = pd.to_datetime(manuais["definida_em"]).dt.strftime("%d/%m/%Y %H:%M")
    st.dataframe(manuais.rename(columns={"id_parcela": "ID Parcela", "categoria": "Categoria", "motivo": "Motivo",
                                         "usuario": "Usuário", "definida_em": "Definida em"}), hide_index=True)
    c1, c2 = st.columns([3, 1])
    remover = c1.selectbox("Remover classificação manual de", manuais["id_parcela"].tolist(), index=None,
                           placeholder="Escolha...", key="cfg_remover")
    if c2.button("Remover", disabled=remover is None, key="cfg_btn_remover"):
        classificacao.remover_manual(con, remover, usuario)
        st.success("Removida. O registro volta a seguir as regras.")
        st.rerun()


def _inclusao(con, usuario):
    st.caption("Regra atual: todos os registros contam como receita recebida. Se um dia a planilha trouxer "
               "lotes cancelados, estornados ou não liquidados, marque aqui os status que devem ficar FORA "
               "dos indicadores. Eles continuam guardados e aparecem na Conciliação.")
    todos = sorted({str(r[0]) if r[0] is not None else "(vazio)"
                    for r in con.execute("SELECT DISTINCT status_lote FROM transacoes")})
    atuais = status_excluidos(con)
    sel = st.multiselect("Status fora dos indicadores", sorted(set(todos) | set(atuais)), default=atuais,
                         key="cfg_status")
    if st.button("Salvar regra de inclusão", type="primary", key="cfg_salvar_status"):
        definir_status_excluidos(con, sel, usuario)
        st.success("Regra salva.")
        st.rerun()


def _backup(con, usuario):
    st.caption(f"Banco de dados: `{banco.caminho_banco()}`. Os backups ficam na pasta `backups` ao lado dele.")
    if st.button("Gerar backup agora", type="primary", key="cfg_backup"):
        arq = banco.fazer_backup()
        banco.registrar_auditoria(con, usuario, "backup", str(arq))
        st.session_state["ultimo_backup"] = str(arq)
    if st.session_state.get("ultimo_backup"):
        arq = Path(st.session_state["ultimo_backup"])
        st.success(f"Backup salvo em `{arq}`.")
        st.download_button("⬇️ Baixar uma cópia do backup", data=arq.read_bytes(), file_name=arq.name,
                           mime="application/octet-stream", key="cfg_baixar_backup")

    st.markdown("**Restaurar um backup**")
    st.warning("Restaurar substitui todos os dados atuais pelos do backup. Antes disso, o sistema salva "
               "automaticamente uma cópia dos dados atuais.")
    up = st.file_uploader("Arquivo de backup (.db)", type=["db"], key="cfg_upload_backup")
    if up:
        tmp = Path(tempfile.mkdtemp()) / up.name
        tmp.write_bytes(up.getvalue())
        try:
            n = banco.validar_backup(tmp)
        except ValueError as e:
            st.error(str(e))
            return
        st.info(f"Backup válido com {inteiro(n)} registro(s).")
        ok = st.checkbox("Entendo que os dados atuais serão substituídos.", key="cfg_conf_restaurar")
        if st.button("Restaurar", disabled=not ok, key="cfg_restaurar"):
            banco.restaurar_backup(tmp)
            banco.registrar_auditoria(con, usuario, "restauracao_backup", up.name)
            st.cache_data.clear()
            st.cache_resource.clear()            # verifica o arquivo de novo e libera as gravações
            st.session_state.pop("_con", None)
            st.success("Backup restaurado.")
            st.rerun()


ACOES = {"importacao": "Importação", "classificacao_manual": "Classificação manual",
         "classificacao_manual_removida": "Classificação manual removida", "regras_alteradas": "Regras alteradas",
         "grupos_alterados": "Receitas alteradas", "atualizacao_regras": "Atualização automática de regras",
         "resolucao_conflito": "Conflito resolvido", "regra_inclusao_status": "Regra de inclusão alterada",
         "backup": "Backup", "restauracao_backup": "Backup restaurado", "exportacao_excel": "Exportação Excel",
         "exportacao_csv": "Exportação CSV", "importacao_excluida": "Importação excluída",
         "login": "Entrada no sistema", "login_falhou": "Tentativa de entrada recusada", "logout": "Saída do sistema",
         "sessao_expirada": "Sessão expirada", "usuario_criado": "Usuário criado",
         "usuario_alterado": "Usuário alterado", "senha_alterada": "Senha alterada",
         "senha_redefinida": "Senha redefinida pelo administrador"}


def _auditoria(con):
    linhas = pd.DataFrame([dict(r) for r in con.execute(
        "SELECT momento, usuario, acao, detalhes FROM auditoria ORDER BY id DESC LIMIT 500")])
    if linhas.empty:
        st.caption("Nenhum registro.")
        return
    linhas["momento"] = pd.to_datetime(linhas["momento"]).dt.strftime("%d/%m/%Y %H:%M:%S")
    linhas["acao"] = linhas["acao"].map(lambda a: ACOES.get(a, a))
    linhas["detalhes"] = linhas["detalhes"].fillna("").str.slice(0, 300)
    st.dataframe(linhas.rename(columns={"momento": "Data/hora", "usuario": "Usuário", "acao": "Ação",
                                        "detalhes": "Detalhes"}), hide_index=True)
