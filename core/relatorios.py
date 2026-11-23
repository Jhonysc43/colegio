"""Relatórios e exportações (Excel e CSV).

- Todo relatório traz o período utilizado, a data de geração e os filtros aplicados.
- A exportação de dados traz TODAS as colunas originais, com os valores exatamente
  como vieram da planilha, mais as colunas calculadas pelo sistema (Receita,
  Categoria, Meio, Data de entrada), identificadas como tal.
- Valores monetários vão para o Excel como número (formato R$), não como texto.
- CSV no padrão brasileiro: separador ";" e vírgula decimal (abre direto no Excel).
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .conciliacao import executar_verificacoes
from .formatos import formatar_data
from .marca import NOME_SISTEMA
from .indicadores import boletos_por_dia, receita_diaria, resumo_por, totais_por_dia

FORMATO_RS = '"R$" #,##0.00'
AZUL = "0B2545"


@dataclass
class Tabela:
    nome: str                       # nome da aba
    dados: pd.DataFrame
    moedas: list[str] = field(default_factory=list)   # colunas em reais
    datas: list[str] = field(default_factory=list)    # colunas AAAA-MM-DD a exibir como DD/MM/AAAA


@dataclass
class Relatorio:
    titulo: str
    periodo: str
    filtros: str
    tabelas: list[Tabela]
    gerado_em: str = field(default_factory=lambda: datetime.now().strftime("%d/%m/%Y %H:%M"))


def _reais(df: pd.DataFrame, mapa: dict[str, str]) -> pd.DataFrame:
    """Converte colunas *_cent em reais (2 casas) e renomeia."""
    out = df.copy()
    for c in mapa:
        if c.endswith("_cent") and c in out:
            out[c] = (out[c].astype("int64") / 100).round(2)
    return out[[c for c in mapa if c in out]].rename(columns=mapa)


RESUMO = {"pagamentos": "Pagamentos", "registros": "Linhas", "bruto_cent": "Valor bruto",
          "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido"}
MOEDAS = ["Valor bruto", "Custo financeiro", "Valor líquido"]


def tabela_dados(df: pd.DataFrame, colunas_originais: list[str]) -> Tabela:
    calc = pd.DataFrame({
        "[Sistema] Data de entrada": df["data_entrada"].values,
        "[Sistema] Receita": df["receita"].values,
        "[Sistema] Categoria": df["categoria"].values,
        "[Sistema] Origem da classificação": df["origem_classificacao"].values,
        "[Sistema] Meio de pagamento": df["meio"].values,
    })
    originais = pd.DataFrame(list(df["dados_originais"].map(json.loads)))
    if originais.empty:
        originais = pd.DataFrame(columns=colunas_originais)
    ordem = [c for c in colunas_originais if c in originais] + [c for c in originais if c not in colunas_originais]
    return Tabela("Dados", pd.concat([calc, originais[ordem].reset_index(drop=True)], axis=1),
                  datas=["[Sistema] Data de entrada"])


def tabela_por(df: pd.DataFrame, coluna: str, rotulo: str, nome: str) -> Tabela:
    t = resumo_por(df, coluna).sort_values("bruto_cent", ascending=False)
    total = t["bruto_cent"].sum()
    t["part"] = (t["bruto_cent"] / total * 100).round(2) if total else 0
    out = _reais(t, {coluna: rotulo, **RESUMO, "part": "% do bruto"})
    pagamentos = int(df["id_parcela"].nunique()) if not df.empty else 0
    return Tabela(nome, _com_total(out, rotulo, pagamentos), moedas=MOEDAS)


def _com_total(t: pd.DataFrame, rotulo: str, pagamentos: int) -> pd.DataFrame:
    """Linha TOTAL. Pagamentos = ID Parcela distintos no total (não é a soma dos grupos)."""
    if t.empty:
        return t
    total = {rotulo: "TOTAL", "Pagamentos": pagamentos}
    for c in t.columns:
        if c in MOEDAS:
            total[c] = round(t[c].sum(), 2)
        elif c in ("Linhas",):
            total[c] = int(t[c].sum())
        elif c == "% do bruto":
            total[c] = 100.0
    return pd.concat([t, pd.DataFrame([total])], ignore_index=True)


def demonstrativo_diario(df: pd.DataFrame) -> list[Tabela]:
    nomes = {"data_entrada": "Data", **RESUMO, "qtd_pix": "Pix", "qtd_cartao": "Cartões", "qtd_boleto": "Boletos"}
    tot = totais_por_dia(df)
    tot["var_bruto_pct"] = tot["var_bruto_pct"]
    t1 = _reais(tot, {**nomes, "var_bruto_pct": "Var. bruto % (dia anterior)"})
    t2 = _reais(receita_diaria(df), {"data_entrada": "Data", "receita": "Receita", **{k: v for k, v in nomes.items()
                                                                                   if k != "data_entrada"}})
    return [Tabela("Totais por dia", t1, moedas=MOEDAS, datas=["Data"]),
            Tabela("Dia x receita", t2, moedas=MOEDAS, datas=["Data"])]


def demonstrativo_mensal(df: pd.DataFrame) -> list[Tabela]:
    d = df.assign(mes=df["data_entrada"].str[:7])
    t1 = resumo_por(d, "mes").sort_values("mes")
    t2 = resumo_por(d, ["mes", "receita"]).sort_values(["mes", "bruto_cent"], ascending=[True, False])
    t3 = resumo_por(d, ["mes", "meio"]).sort_values(["mes", "meio"])
    fmt = lambda s: s.map(lambda m: f"{m[5:7]}/{m[:4]}")
    for t in (t1, t2, t3):
        t["mes"] = fmt(t["mes"])
    return [Tabela("Totais por mês", _reais(t1, {"mes": "Mês", **RESUMO}), moedas=MOEDAS),
            Tabela("Mês x receita", _reais(t2, {"mes": "Mês", "receita": "Receita", **RESUMO}), moedas=MOEDAS),
            Tabela("Mês x meio", _reais(t3, {"mes": "Mês", "meio": "Meio de pagamento", **RESUMO}), moedas=MOEDAS)]


def relatorio_boletos(df: pd.DataFrame) -> list[Tabela]:
    b = df[df["meio"] == "Boleto"]
    dia = boletos_por_dia(b)
    dia["lotes"] = dia["lotes"].map(", ".join)
    t1 = _reais(dia, {"data_entrada": "Data de processamento", "pagamentos": "Qtd. boletos",
                      "pagos_via_boleto": "Quitados via boleto", "pagos_via_pix": "Quitados via Pix",
                      "bruto_cent": "Valor bruto", "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido",
                      "status_lote": "Status do lote", "lotes": "ID do Lote"})
    if b.empty:
        ind = pd.DataFrame()
    else:
        g = b.groupby("id_parcela")
        ind = g.agg(nr_pedido=("nr_pedido", "first"), receita=("receita", "first"),
                    forma=("forma_pagamento", "first"), data_criacao=("data_criacao", "min"),
                    data_pagamento=("data_pagamento", "max"), data_liquidacao=("data_liquidacao", "max"),
                    data_entrada=("data_entrada", "max"), status=("status_lote", "first"), lote=("id_lote", "first"),
                    linhas=("id", "size"), bruto_cent=("valor_bruto_cent", "sum"),
                    custo_cent=("custo_financeiro_cent", "sum"), liquido_cent=("valor_liquido_cent", "sum"))
        ind = ind.reset_index().sort_values(["data_entrada", "receita", "id_parcela"])
    t2 = _reais(ind, {"id_parcela": "ID Parcela", "nr_pedido": "Nº do Pedido", "receita": "Receita",
                      "forma": "Quitado via", "data_criacao": "Data de criação", "data_pagamento": "Data de pagamento",
                      "data_liquidacao": "Data de liquidação", "data_entrada": "Data de processamento",
                      "bruto_cent": "Valor bruto", "custo_cent": "Custo financeiro", "liquido_cent": "Valor líquido",
                      "status": "Status do lote", "lote": "ID do Lote", "linhas": "Linhas"}) if not ind.empty else ind
    datas = ["Data de criação", "Data de pagamento", "Data de liquidação", "Data de processamento"]
    return [Tabela("Boletos por dia", t1, moedas=MOEDAS, datas=["Data de processamento"]),
            Tabela("Boletos individuais", t2, moedas=MOEDAS, datas=datas)]


def relatorio_inconsistencias(con, df: pd.DataFrame) -> list[Tabela]:
    verif = executar_verificacoes(con, df)
    gravidade = {"erro": "Erro", "atencao": "Atenção", "info": "Informativo"}
    resumo_v = pd.DataFrame([{"Verificação": v.titulo, "Gravidade": gravidade[v.gravidade],
                              "Registros": v.quantidade, "Descrição": v.descricao} for v in verif])
    linhas = []
    for v in verif:
        if v.gravidade == "info" and v.codigo == "identicas":
            continue
        for _, r in v.registros.iterrows():
            linhas.append({"Verificação": v.titulo, "Gravidade": gravidade[v.gravidade],
                           "Data de entrada": r["data_entrada"], "ID Parcela": r["id_parcela"],
                           "ID da Venda": r["id_venda"], "Nº do Pedido": r["nr_pedido"],
                           "Receita": r.get("receita"), "Valor bruto": r["valor_bruto_cent"] / 100,
                           "Custo financeiro": r["custo_financeiro_cent"] / 100,
                           "Valor líquido": r["valor_liquido_cent"] / 100,
                           "Detalhe": r.get("motivo", "") if isinstance(r.get("motivo", ""), str) else "",
                           "Linha no Excel": r["linha_planilha"]})
    return [Tabela("Resumo das verificações", resumo_v),
            Tabela("Registros sinalizados", pd.DataFrame(linhas), moedas=MOEDAS, datas=["Data de entrada"])]


TIPOS = {
    "dados": "Dados filtrados (todas as colunas)",
    "diario": "Demonstrativo diário",
    "mensal": "Demonstrativo mensal",
    "receita": "Por receita",
    "meio": "Por meio de pagamento",
    "boletos": "Boletos processados",
    "inconsistencias": "Inconsistências",
}


def montar(con, tipo: str, df: pd.DataFrame, periodo: str, filtros: str,
           colunas_originais: list[str] | None = None) -> Relatorio:
    if tipo == "dados":
        tabelas = [tabela_dados(df, colunas_originais or [])]
    elif tipo == "diario":
        tabelas = demonstrativo_diario(df)
    elif tipo == "mensal":
        tabelas = demonstrativo_mensal(df)
    elif tipo == "receita":
        tabelas = [tabela_por(df, "receita", "Receita", "Por receita"),
                   tabela_por(df, "categoria", "Categoria", "Por categoria")]
    elif tipo == "meio":
        tabelas = [tabela_por(df, "meio", "Meio de pagamento", "Por meio"),
                   tabela_por(df, "forma_pagamento", "Forma de pagamento", "Por forma")]
    elif tipo == "boletos":
        tabelas = relatorio_boletos(df)
    elif tipo == "inconsistencias":
        tabelas = relatorio_inconsistencias(con, df)
    else:
        raise ValueError(f"Tipo de relatório desconhecido: {tipo}")
    return Relatorio(TIPOS[tipo], periodo, filtros, tabelas)


def gerar_excel(rel: Relatorio) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    usados = set()
    for t in rel.tabelas:
        nome = t.nome[:31]
        while nome in usados:
            nome = nome[:28] + f"_{len(usados)}"
        usados.add(nome)
        ws = wb.create_sheet(nome)
        ws["A1"] = f"{NOME_SISTEMA} — {rel.titulo}"
        ws["A1"].font = Font(bold=True, size=13, color=AZUL)
        ws["A2"] = f"Período: {rel.periodo}"
        ws["A3"] = f"Filtros: {rel.filtros}"
        ws["A4"] = f"Gerado em: {rel.gerado_em}"
        inicio = 6
        df = t.dados
        for j, col in enumerate(df.columns, start=1):
            c = ws.cell(row=inicio, column=j, value=str(col))
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor=AZUL)
            c.alignment = Alignment(wrap_text=True, vertical="center")
        for i, linha in enumerate(df.itertuples(index=False), start=inicio + 1):
            for j, (col, v) in enumerate(zip(df.columns, linha), start=1):
                if v is not None and not isinstance(v, (str, int, float, bool)):
                    v = str(v)
                if isinstance(v, float) and pd.isna(v):
                    v = None
                if col in t.datas and isinstance(v, str) and len(v) >= 10 and v[4] == "-":
                    v = formatar_data(v)
                cel = ws.cell(row=i, column=j, value=v)
                if col in t.moedas:
                    cel.number_format = FORMATO_RS
            if df.columns.size and str(linha[0]) == "TOTAL":
                for j in range(1, df.columns.size + 1):
                    ws.cell(row=i, column=j).font = Font(bold=True)
        for j, col in enumerate(df.columns, start=1):
            amostra = [len(str(col))] + [len(str(v)) for v in df.iloc[:200, j - 1]]
            ws.column_dimensions[get_column_letter(j)].width = min(max(amostra) + 2, 45)
        ws.freeze_panes = ws.cell(row=inicio + 1, column=1)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def gerar_csv(rel: Relatorio, indice: int = 0) -> bytes:
    t = rel.tabelas[indice]
    df = t.dados.copy()
    for c in t.datas:
        if c in df:
            df[c] = df[c].map(lambda v: formatar_data(v) if isinstance(v, str) and len(v) >= 10 and v[4] == "-" else v)
    cab = (f"{NOME_SISTEMA} — {rel.titulo} — {t.nome}\nPeríodo: {rel.periodo}\nFiltros: {rel.filtros}\n"
           f"Gerado em: {rel.gerado_em}\n\n")
    corpo = df.to_csv(sep=";", decimal=",", index=False)
    return (cab + corpo).encode("utf-8-sig")
