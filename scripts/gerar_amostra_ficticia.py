"""Gera uma planilha FICTÍCIA a partir de uma planilha real, para publicar o projeto como amostra.

Uso: python scripts/gerar_amostra_ficticia.py <planilha real.xlsx> <saída.xlsx>

Mantém a estrutura (colunas, cabeçalho, linhas de split, tabela dinâmica no rodapé, formatos de data,
prefixos dos pedidos, combinações de forma e meio de pagamento) e troca:
- nomes de pagadores e titulares de cartão por nomes fictícios;
- ID Parcela, ID do Lote, ID da Venda, Nº do Pedido, Nº do documento e ID CNAB por valores inventados,
  preservando quais linhas pertencem ao mesmo pagamento;
- os valores: cada linha é multiplicada por um fator aleatório, com Valor Líquido = Bruto − Custo exato.
A coluna "Sistemas" (fórmula) é gravada como valor e o rodapé é recalculado. A tabela dinâmica (que
guarda uma cópia interna dos dados originais), as imagens e o nome do autor do arquivo são removidos.
"""
from __future__ import annotations

import random
import re
import string
import sys
import uuid
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import openpyxl

SEMENTE = 20261109
LINHA_CABECALHO = 7


def main(entrada: str, saida: str) -> None:
    rnd = random.Random(SEMENTE)
    valores = openpyxl.load_workbook(entrada, data_only=True).worksheets[0]   # para ler "Sistemas"
    wb = openpyxl.load_workbook(entrada)
    ws = wb.worksheets[0]
    cab = [c.value for c in ws[LINHA_CABECALHO]]
    col = {nome: i + 1 for i, nome in enumerate(cab) if nome}

    mapas: dict[str, dict] = {k: {} for k in ("parcela", "lote", "venda", "pedido", "pessoa", "titular")}

    def novo(tipo, chave, gerar):
        m = mapas[tipo]
        if chave not in m:
            m[chave] = gerar(len(m) + 1)
        return m[chave]

    def pedido(token: str) -> str:
        p = re.match(r"([A-Za-z]+)(\d+)", token)
        if not p:
            return token
        letras, digitos = p.groups()
        return novo("pedido", token, lambda n: f"{letras}{str(n).zfill(len(digitos))[-len(digitos):]}")

    def troca_pedidos(texto):
        if not isinstance(texto, str):
            return texto
        return re.sub(r"\b[A-Z]{1,5}\d{5,}\b", lambda m: pedido(m.group(0)), texto)

    def dinheiro(v) -> Decimal:
        return Decimal(str(v or 0)).quantize(Decimal("0.01"))

    linhas = []
    r = LINHA_CABECALHO + 1
    while ws.cell(row=r, column=col["ID Parcela"]).value not in (None, ""):
        linhas.append(r)
        r += 1

    for r in linhas:
        c = lambda nome: ws.cell(row=r, column=col[nome])  # noqa: E731
        c("ID Parcela").value = novo("parcela", c("ID Parcela").value, lambda n: 900000000 + n)
        c("ID do Lote").value = novo("lote", c("ID do Lote").value,
                                     lambda n: str(uuid.uuid5(uuid.NAMESPACE_OID, f"lote{n}")))
        c("ID da Venda").value = novo("venda", c("ID da Venda").value,
                                      lambda n: str(uuid.uuid5(uuid.NAMESPACE_OID, f"venda{n}")))
        c("Nº do Pedido").value = ",".join(pedido(p.strip()) for p in str(c("Nº do Pedido").value).split(","))
        c("Descrição").value = troca_pedidos(c("Descrição").value)
        c("Pagador").value = novo("pessoa", c("Pagador").value, lambda n: f"PAGADOR FICTÍCIO {n:03d}")
        tit = c("Titular do cartão").value
        if tit and tit != "Não informado":
            c("Titular do cartão").value = novo("titular", tit, lambda n: f"Titular Fictício {n:02d}")
        doc = c("Nº do documento").value
        if doc:
            c("Nº do documento").value = "".join(rnd.choice(string.digits) for _ in str(doc))
        cnab = c("ID CNAB").value
        if cnab:
            c("ID CNAB").value = "".join(rnd.choice(string.ascii_letters + string.digits) for _ in str(cnab))
        # valores: mesmo fator para bruto e custo da linha; líquido = bruto − custo
        fator = Decimal(str(round(rnd.uniform(0.55, 1.6), 3)))
        bruto = (dinheiro(c("Valor Bruto").value) * fator).quantize(Decimal("0.01"), ROUND_HALF_UP)
        custo = (dinheiro(c("Custo Financeiro").value) * fator).quantize(Decimal("0.01"), ROUND_HALF_UP)
        custo = min(custo, bruto)
        c("Valor Bruto").value = float(bruto)
        c("Custo Financeiro").value = float(custo)
        c("Valor Líquido").value = float(bruto - custo)
        # Sistemas: grava o valor calculado (a fórmula perderia o resultado ao salvar)
        c("Sistemas").value = valores.cell(row=r, column=col["Sistemas"]).value

    _recalcular_rodape(ws, col, linhas)
    # A tabela dinâmica guarda uma cópia interna de TODOS os dados originais (pivotCache):
    # é removida; os totais do rodapé ficam como valores comuns. Imagens (logotipos) e o autor também saem.
    for planilha in wb.worksheets:
        planilha._pivots = []
        planilha._images = []
        planilha._charts = []
    wb.properties.creator = "Amostra fictícia"
    wb.properties.lastModifiedBy = "Amostra fictícia"
    wb.properties.title = "Planilha fictícia para demonstração"
    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    wb.save(saida)
    print(f"Planilha fictícia gerada: {saida} ({len(linhas)} linhas, "
          f"{len(mapas['parcela'])} parcelas, {len(mapas['pessoa'])} pagadores fictícios)")


def _recalcular_rodape(ws, col, linhas):
    """Recalcula a tabela dinâmica (Forma de Pagamento > Sistemas) com os valores novos."""
    dados = []
    for r in linhas:
        g = lambda n: ws.cell(row=r, column=col[n]).value  # noqa: E731
        dados.append((g("Forma de Pagamento"), g("Sistemas"), Decimal(str(g("Valor Bruto"))),
                      Decimal(str(g("Custo Financeiro"))), Decimal(str(g("Valor Líquido")))))
    formas = {d[0] for d in dados}
    pai = None
    for r in range(linhas[-1] + 1, ws.max_row + 1):
        rotulo = ws.cell(row=r, column=4).value
        if not isinstance(rotulo, str) or ws.cell(row=r, column=5).value is None:
            continue
        if rotulo.startswith(("Rótulos", "Soma", "Contagem")):
            continue
        if rotulo == "Total Geral":
            sel = dados
        elif rotulo in formas:
            pai, sel = rotulo, [d for d in dados if d[0] == rotulo]
        else:
            sel = [d for d in dados if d[0] == pai and d[1] == rotulo]
        ws.cell(row=r, column=5).value = float(sum(d[2] for d in sel))
        ws.cell(row=r, column=6).value = float(sum(d[3] for d in sel))
        ws.cell(row=r, column=7).value = float(sum(d[4] for d in sel))
        ws.cell(row=r, column=8).value = len(sel)
        ws.cell(row=r, column=9).value = len(sel)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    main(sys.argv[1], sys.argv[2])
