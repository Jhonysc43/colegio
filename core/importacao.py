"""Importação de planilhas Excel em duas fases.

1. `analisar_arquivo()` lê a planilha, identifica o cabeçalho e as colunas,
   valida valores e datas, separa linhas de resumo (tabela dinâmica) e
   detecta duplicidades — sem gravar nada. O resultado é a prévia.
2. `confirmar_importacao()` grava no banco, dentro de uma transação única,
   a partir da prévia aprovada pelo usuário.

Identificação de registros (decisão baseada na planilha de referência):
- "ID Parcela" NÃO é único por linha: um mesmo pagamento aparece em várias
  linhas quando o valor é dividido (split). Ex.: um mesmo ID Parcela tem
  uma linha de R$ 0,12 (líquido) e outra de R$ 0,49 (custo).
- "ID da Venda" é único por linha e é usado como chave do registro.
  Na ausência dele, usa-se um hash de todas as colunas da linha.
- Reimportar o mesmo registro (mesma chave, mesmo conteúdo) não duplica.
  Mesma chave com conteúdo diferente vira CONFLITO para decisão manual;
  o registro original nunca é sobrescrito automaticamente.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

from .banco import agora, fazer_backup, registrar_auditoria, transacao
from .formatos import DataInvalida, ValorInvalido, interpretar_data, para_centavos

COLUNAS_OBRIGATORIAS = ["ID Parcela", "Nº do Pedido", "Valor Bruto", "Custo Financeiro", "Valor Líquido"]
COLUNAS_VALOR = ["Valor Bruto", "Custo Financeiro", "Valor Líquido"]
COLUNAS_DATA = {
    "Data de Criação": "data_criacao",
    "Data de Pagamento": "data_pagamento",
    "Data de Liquidação": "data_liquidacao",
}
COLUNAS_DATA_HORA = ["Data/Hora de Criação", "Data/Hora de Pagamento", "Data da Confirmação do Serviço"]
MARCADORES_RESUMO = ("Rótulos de Linha", "Total Geral", "Soma de ", "Contagem de ")
LINHAS_BUSCA_CABECALHO = 50
# Colunas auxiliares acrescentadas manualmente na planilha (fórmulas), que não
# vêm da intermediadora. Ficam preservadas, mas não entram na comparação de
# conteúdo: se o Excel recalcular a fórmula, o registro não vira "conflito".
COLUNAS_FORA_DO_HASH = {"Sistemas"}


class ErroImportacao(Exception):
    pass


@dataclass
class Alerta:
    linha: int | None
    coluna: str | None
    tipo: str
    mensagem: str


@dataclass
class LinhaDados:
    linha: int                 # número da linha no Excel (1 = primeira linha)
    dados: dict                # todas as colunas originais (valores como vieram)
    chave: str
    hash_conteudo: str
    bruto: int | None
    custo: int | None
    liquido: int | None
    datas: dict                # campo_banco -> 'AAAA-MM-DD' | None


@dataclass
class Analise:
    arquivo: str
    hash_arquivo: str
    aba: str
    abas_disponiveis: list[str]
    linha_cabecalho: int
    colunas: list[str]
    linhas: list[LinhaDados] = field(default_factory=list)
    linhas_ignoradas: list[tuple[int, str, list]] = field(default_factory=list)  # (linha, motivo, conteúdo)
    linhas_vazias: int = 0
    alertas: list[Alerta] = field(default_factory=list)
    duplicadas_no_arquivo: dict[str, list[int]] = field(default_factory=dict)
    data_liquidacao_sugerida: str | None = None

    # --- resumos para a tela de prévia ---
    def totais(self) -> dict:
        return {
            "registros": len(self.linhas),
            "pagamentos (ID Parcela distintos)": len({_texto_id(l.dados.get("ID Parcela")) for l in self.linhas}),
            "bruto_cent": sum(l.bruto or 0 for l in self.linhas),
            "custo_cent": sum(l.custo or 0 for l in self.linhas),
            "liquido_cent": sum(l.liquido or 0 for l in self.linhas),
        }

    def alertas_agrupados(self) -> list[tuple[str, str | None, int, list[int]]]:
        grupos: dict[tuple[str, str | None], list[int]] = defaultdict(list)
        for a in self.alertas:
            grupos[(a.tipo, a.coluna)].append(a.linha)
        return [(t, c, len(ls), ls[:20]) for (t, c), ls in grupos.items()]


def _hash_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(1 << 20), b""):
            h.update(bloco)
    return h.hexdigest()


def _json_seguro(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _normalizar_para_hash(v):
    """Célula com texto vazio e célula vazia são equivalentes (o Excel alterna
    entre as duas ao salvar); números inteiros e decimais iguais também."""
    if isinstance(v, str):
        v = v.strip()
        return v or None
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return v


def _normalizar_cabecalho(v) -> str | None:
    if v is None:
        return None
    return " ".join(str(v).split())


def _texto_id(v) -> str | None:
    """IDs numéricos podem vir como 900000001 ou 900000001.0; padroniza em texto."""
    if v is None or (isinstance(v, str) and v.strip() == ""):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def _abrir(caminho: Path):
    sufixo = caminho.suffix.lower()
    if sufixo in (".xlsx", ".xlsm"):
        # read_only: lê linha a linha, adequado a arquivos grandes.
        # data_only: usa o último valor calculado das fórmulas (coluna "Sistemas").
        return openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    if sufixo == ".xls":
        raise ErroImportacao(
            "Arquivos .xls (formato antigo) ainda não são suportados nesta instalação. "
            "Abra o arquivo no Excel e salve como .xlsx."
        )
    raise ErroImportacao(f"Formato não suportado: {sufixo}. Use .xlsx.")


def listar_abas(caminho: str | Path) -> list[str]:
    wb = _abrir(Path(caminho))
    try:
        return list(wb.sheetnames)
    finally:
        wb.close()


def analisar_arquivo(caminho: str | Path, aba: str | None = None, nome_original: str | None = None) -> Analise:
    caminho = Path(caminho)
    wb = _abrir(caminho)
    try:
        abas = wb.sheetnames
        ws = wb[aba] if aba else wb[abas[0]]

        linhas_iter = ws.iter_rows(values_only=True)
        cabecalho, linha_cab, buffer = None, None, []
        for i, valores in enumerate(linhas_iter, start=1):
            nomes = [_normalizar_cabecalho(v) for v in valores]
            if sum(1 for c in COLUNAS_OBRIGATORIAS if c in nomes) >= 3:
                cabecalho, linha_cab = nomes, i
                break
            if i >= LINHAS_BUSCA_CABECALHO:
                break
        if not cabecalho:
            raise ErroImportacao(
                f"Não encontrei o cabeçalho na aba '{ws.title}' (procurei nas {LINHAS_BUSCA_CABECALHO} "
                f"primeiras linhas por colunas como {', '.join(COLUNAS_OBRIGATORIAS)})."
            )
        faltando = [c for c in COLUNAS_OBRIGATORIAS if c not in cabecalho]
        if faltando:
            raise ErroImportacao(f"Colunas obrigatórias ausentes: {', '.join(faltando)}.")

        # Colunas sem nome no cabeçalho são preservadas como "Coluna sem título N".
        colunas, vistos = [], Counter()
        ultima = max(i for i, c in enumerate(cabecalho) if c) + 1
        for idx, nome in enumerate(cabecalho[:ultima]):
            nome = nome or f"Coluna sem título {idx + 1}"
            vistos[nome] += 1
            colunas.append(nome if vistos[nome] == 1 else f"{nome} ({vistos[nome]})")

        analise = Analise(
            arquivo=nome_original or caminho.name,
            hash_arquivo=_hash_arquivo(caminho),
            aba=ws.title,
            abas_disponiveis=abas,
            linha_cabecalho=linha_cab,
            colunas=colunas,
        )

        em_resumo = False
        chaves: dict[str, list[int]] = defaultdict(list)
        liquidacoes = Counter()

        for n, valores in enumerate(linhas_iter, start=linha_cab + 1):
            valores = list(valores[:ultima]) + [None] * max(0, ultima - len(valores))
            if all(v is None or (isinstance(v, str) and v.strip() == "") for v in valores):
                analise.linhas_vazias += 1
                continue
            dados = {col: _json_seguro(v) for col, v in zip(colunas, valores)}
            id_parcela = _texto_id(dados.get("ID Parcela"))
            id_venda = _texto_id(dados.get("ID da Venda"))

            textos = [str(v) for v in valores if isinstance(v, str)]
            if any(t.startswith(MARCADORES_RESUMO) for t in textos):
                em_resumo = True
            if em_resumo or (not id_parcela and not id_venda):
                motivo = "resumo/tabela dinâmica" if em_resumo else "linha sem ID Parcela e sem ID da Venda"
                analise.linhas_ignoradas.append((n, motivo, [v for v in valores if v is not None]))
                continue

            conteudo = json.dumps({k: _normalizar_para_hash(v) for k, v in dados.items()
                                   if k not in COLUNAS_FORA_DO_HASH}, sort_keys=True, ensure_ascii=False, default=str)
            hash_conteudo = hashlib.sha256(conteudo.encode()).hexdigest()
            chave = f"venda:{id_venda}" if id_venda else f"hash:{hash_conteudo}"
            chaves[chave].append(n)

            # Valores
            vals = {}
            for col in COLUNAS_VALOR:
                try:
                    vals[col] = para_centavos(dados.get(col))
                    if vals[col] is None:
                        analise.alertas.append(Alerta(n, col, "valor_vazio", f"{col} vazio"))
                except ValorInvalido as e:
                    vals[col] = None
                    analise.alertas.append(Alerta(n, col, "valor_invalido", str(e)))
            b, c, l = vals["Valor Bruto"], vals["Custo Financeiro"], vals["Valor Líquido"]
            if None not in (b, c, l) and b - c != l:
                analise.alertas.append(Alerta(
                    n, "Valor Líquido", "divergencia_liquido",
                    f"Bruto − Custo = {(b - c) / 100:.2f}, mas Líquido = {l / 100:.2f}"))
            for col, v in vals.items():
                if v is not None and v < 0:
                    analise.alertas.append(Alerta(n, col, "valor_negativo", f"{col} negativo ({v / 100:.2f})"))

            # Datas
            datas = {}
            for col, campo in COLUNAS_DATA.items():
                if col not in dados:
                    continue
                try:
                    dt, corrigida = interpretar_data(dados.get(col))
                    datas[campo] = dt.date().isoformat() if dt else None
                    if corrigida:
                        analise.alertas.append(Alerta(
                            n, col, "data_formato_corrigido",
                            f"'{dados.get(col)}' fora do padrão; interpretada como {dt:%d/%m/%Y}"))
                except DataInvalida as e:
                    datas[campo] = None
                    analise.alertas.append(Alerta(n, col, "data_invalida", str(e)))
            for col in COLUNAS_DATA_HORA:
                if dados.get(col) is not None:
                    try:
                        interpretar_data(dados.get(col))
                    except DataInvalida as e:
                        analise.alertas.append(Alerta(n, col, "data_invalida", str(e)))
            if datas.get("data_liquidacao"):
                liquidacoes[datas["data_liquidacao"]] += 1
            if datas.get("data_pagamento") and datas.get("data_criacao") and datas["data_pagamento"] < datas["data_criacao"]:
                analise.alertas.append(Alerta(n, "Data de Pagamento", "data_inconsistente",
                                              "Data de pagamento anterior à data de criação da linha (comum em split confirmado depois do pagamento)"))

            status = dados.get("Status do Lote")
            if status is not None and str(status).strip().lower() != "pago":
                analise.alertas.append(Alerta(n, "Status do Lote", "status_diferente",
                                              f"Status do lote = '{status}'"))

            analise.linhas.append(LinhaDados(n, dados, chave, hash_conteudo, b, c, l, datas))

        analise.duplicadas_no_arquivo = {k: v for k, v in chaves.items() if len(v) > 1}
        for k, ls in analise.duplicadas_no_arquivo.items():
            for n in ls:
                analise.alertas.append(Alerta(n, "ID da Venda", "duplicada_no_arquivo",
                                              f"Mesmo identificador nas linhas {ls}"))
        if liquidacoes:
            analise.data_liquidacao_sugerida = liquidacoes.most_common(1)[0][0]
        return analise
    finally:
        wb.close()


@dataclass
class ResultadoImportacao:
    importacao_id: int
    inseridas: int
    ja_existentes: int
    conflitos: int
    ignoradas: int
    alertas: int


def arquivo_ja_importado(con, hash_arquivo: str) -> list[dict]:
    return [dict(r) for r in con.execute(
        "SELECT id, arquivo, processado_em, data_entrada FROM importacoes WHERE hash_arquivo = ?"
        " AND excluida_em IS NULL", (hash_arquivo,))]


def confirmar_importacao(con, analise: Analise, data_entrada: str, usuario: str | None = None,
                         duplicadas: str = "manter_uma") -> ResultadoImportacao:
    """Grava a análise aprovada.

    data_entrada: 'AAAA-MM-DD' informada pelo usuário (data de entrada das receitas).
    duplicadas: tratamento de linhas repetidas DENTRO do arquivo:
        'manter_uma'   -> grava a primeira ocorrência; as demais ficam registradas como alerta;
        'manter_todas' -> grava todas (cada uma recebe chave própria).
    """
    datetime.strptime(data_entrada, "%Y-%m-%d")  # valida
    if duplicadas not in ("manter_uma", "manter_todas"):
        raise ValueError("duplicadas deve ser 'manter_uma' ou 'manter_todas'")

    with transacao(con):
        cur = con.execute(
            "INSERT INTO importacoes (arquivo, hash_arquivo, aba, data_entrada, processado_em, usuario,"
            " linhas_lidas, linhas_inseridas, linhas_ja_existentes, linhas_conflito, linhas_ignoradas,"
            " alertas, colunas, resultado) VALUES (?,?,?,?,?,?,?,0,0,0,?,?,?,?)",
            (analise.arquivo, analise.hash_arquivo, analise.aba, data_entrada, agora(), usuario,
             len(analise.linhas), len(analise.linhas_ignoradas), len(analise.alertas),
             json.dumps(analise.colunas, ensure_ascii=False),
             "concluida_com_alertas" if analise.alertas else "concluida"),
        )
        imp_id = cur.lastrowid
        inseridas = existentes = conflitos = 0
        ocorrencias = Counter()

        for l in analise.linhas:
            ocorrencias[l.chave] += 1
            chave = l.chave
            if ocorrencias[l.chave] > 1:
                if duplicadas == "manter_uma":
                    continue
                chave = f"{l.chave}#{ocorrencias[l.chave]}"

            existente = con.execute("SELECT hash_conteudo FROM transacoes WHERE chave_registro = ?",
                                    (chave,)).fetchone()
            dados_json = json.dumps(l.dados, ensure_ascii=False, default=str)
            if existente:
                if existente["hash_conteudo"] == l.hash_conteudo:
                    existentes += 1
                else:
                    conflitos += 1
                    repetido = con.execute(
                        "SELECT 1 FROM conflitos WHERE chave_registro = ? AND dados_originais = ?"
                        " AND situacao = 'pendente'", (chave, dados_json)).fetchone()
                    if not repetido:  # reimportar o mesmo arquivo não duplica o conflito
                        con.execute("INSERT INTO conflitos (importacao_id, chave_registro, linha_planilha,"
                                    " dados_originais) VALUES (?,?,?,?)", (imp_id, chave, l.linha, dados_json))
                continue

            d = l.dados
            con.execute(
                "INSERT INTO transacoes (importacao_id, linha_planilha, chave_registro, hash_conteudo, id_parcela,"
                " id_lote, id_venda, status_lote, nr_pedido, forma_pagamento, meio_pagamento, valor_bruto_cent,"
                " custo_financeiro_cent, valor_liquido_cent, data_criacao, data_pagamento, data_liquidacao,"
                " data_entrada, estabelecimento, sistemas_planilha, dados_originais)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (imp_id, l.linha, chave, l.hash_conteudo, _texto_id(d.get("ID Parcela")), d.get("ID do Lote"),
                 _texto_id(d.get("ID da Venda")), d.get("Status do Lote"), d.get("Nº do Pedido"),
                 d.get("Forma de Pagamento"), d.get("Meio de Pagamento"), l.bruto, l.custo, l.liquido,
                 l.datas.get("data_criacao"), l.datas.get("data_pagamento"), l.datas.get("data_liquidacao"),
                 data_entrada, d.get("Nome do Estabelecimento"), d.get("Sistemas"), dados_json),
            )
            inseridas += 1

        for a in analise.alertas:
            con.execute("INSERT INTO alertas_importacao (importacao_id, linha_planilha, coluna, tipo, mensagem)"
                        " VALUES (?,?,?,?,?)", (imp_id, a.linha, a.coluna, a.tipo, a.mensagem))
        for n, motivo, conteudo in analise.linhas_ignoradas:
            con.execute("INSERT INTO alertas_importacao (importacao_id, linha_planilha, coluna, tipo, mensagem)"
                        " VALUES (?,?,?,?,?)", (imp_id, n, None, "linha_ignorada",
                                                f"{motivo}: {json.dumps(conteudo, ensure_ascii=False, default=str)[:300]}"))
        con.execute("UPDATE importacoes SET linhas_inseridas=?, linhas_ja_existentes=?, linhas_conflito=? WHERE id=?",
                    (inseridas, existentes, conflitos, imp_id))
        registrar_auditoria(con, usuario, "importacao", json.dumps({
            "importacao_id": imp_id, "arquivo": analise.arquivo, "data_entrada": data_entrada,
            "inseridas": inseridas, "ja_existentes": existentes, "conflitos": conflitos}, ensure_ascii=False))

    return ResultadoImportacao(imp_id, inseridas, existentes, conflitos, len(analise.linhas_ignoradas),
                               len(analise.alertas))


def hash_dados(dados: dict) -> str:
    conteudo = json.dumps({k: _normalizar_para_hash(v) for k, v in dados.items()
                           if k not in COLUNAS_FORA_DO_HASH}, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(conteudo.encode()).hexdigest()


def campos_de_dados(dados: dict) -> dict:
    """Recalcula as colunas de trabalho de `transacoes` a partir das colunas originais
    (usado ao resolver conflitos). Valores ou datas inválidos ficam vazios."""
    vals = {}
    for col, campo in (("Valor Bruto", "valor_bruto_cent"), ("Custo Financeiro", "custo_financeiro_cent"),
                       ("Valor Líquido", "valor_liquido_cent")):
        try:
            vals[campo] = para_centavos(dados.get(col))
        except ValorInvalido:
            vals[campo] = None
    for col, campo in COLUNAS_DATA.items():
        try:
            dt, _ = interpretar_data(dados.get(col))
            vals[campo] = dt.date().isoformat() if dt else None
        except DataInvalida:
            vals[campo] = None
    vals.update({
        "hash_conteudo": hash_dados(dados),
        "id_parcela": _texto_id(dados.get("ID Parcela")), "id_lote": dados.get("ID do Lote"),
        "id_venda": _texto_id(dados.get("ID da Venda")), "status_lote": dados.get("Status do Lote"),
        "nr_pedido": dados.get("Nº do Pedido"), "forma_pagamento": dados.get("Forma de Pagamento"),
        "meio_pagamento": dados.get("Meio de Pagamento"), "estabelecimento": dados.get("Nome do Estabelecimento"),
        "sistemas_planilha": dados.get("Sistemas"),
        "dados_originais": json.dumps(dados, ensure_ascii=False, default=str),
    })
    return vals


# ------------------------------------------------------------ exclusão de importação
@dataclass
class PreviaExclusao:
    importacao_id: int
    arquivo: str
    data_entrada: str
    processado_em: str
    registros: int
    pagamentos: int
    bruto_cent: int
    custo_cent: int
    liquido_cent: int
    ja_existentes: int                 # registros reencontrados: pertencem a outra importação e ficam
    classificacoes_manuais: list[str]  # ID Parcela com classificação manual (ficam guardadas)
    conflitos_pendentes: int           # serão descartados junto com a importação
    bloqueios: list[str]               # motivos que impedem a exclusão
    ja_excluida: bool


def previa_exclusao(con, importacao_id: int) -> PreviaExclusao:
    imp = con.execute("SELECT * FROM importacoes WHERE id = ?", (importacao_id,)).fetchone()
    if not imp:
        raise ValueError(f"Importação nº {importacao_id} não encontrada.")
    tot = con.execute(
        "SELECT COUNT(*), COUNT(DISTINCT id_parcela), COALESCE(SUM(valor_bruto_cent),0),"
        " COALESCE(SUM(custo_financeiro_cent),0), COALESCE(SUM(valor_liquido_cent),0)"
        " FROM transacoes WHERE importacao_id = ?", (importacao_id,)).fetchone()
    manuais = [r[0] for r in con.execute(
        "SELECT DISTINCT m.id_parcela FROM classificacoes_manuais m JOIN transacoes t ON t.id_parcela = m.id_parcela"
        " WHERE t.importacao_id = ? ORDER BY 1", (importacao_id,))]
    pend = con.execute("SELECT COUNT(*) FROM conflitos WHERE importacao_id = ? AND situacao = 'pendente'",
                       (importacao_id,)).fetchone()[0]
    bloqueios = []
    subst = con.execute("SELECT id, chave_registro FROM conflitos WHERE importacao_id = ? AND situacao = 'substituido'",
                        (importacao_id,)).fetchall()
    if subst:
        bloqueios.append(
            f"{len(subst)} registro(s) de importações anteriores foram SUBSTITUÍDOS por dados desta importação "
            f"(conflito nº {', '.join(str(r['id']) for r in subst)}). Excluir apagaria esses registros por "
            "completo. Para desfazer, restaure um backup anterior à decisão do conflito.")
    return PreviaExclusao(importacao_id, imp["arquivo"], imp["data_entrada"], imp["processado_em"], tot[0], tot[1],
                          tot[2], tot[3], tot[4], imp["linhas_ja_existentes"], manuais, pend, bloqueios,
                          imp["excluida_em"] is not None)


def excluir_importacao(con, importacao_id: int, usuario: str | None, caminho_banco=None,
                       pasta_backup=None) -> PreviaExclusao:
    """Remove os registros que ENTRARAM por esta importação. Faz backup antes.

    - Registros que já existiam (reencontrados) pertencem à importação original e ficam.
    - Classificações manuais ficam guardadas: voltam a valer se o registro for importado de novo.
    - Conflitos pendentes desta importação são descartados.
    - A importação continua no histórico, marcada como excluída.
    """
    p = previa_exclusao(con, importacao_id)
    if p.ja_excluida:
        raise ValueError("Esta importação já foi excluída.")
    if p.bloqueios:
        raise ValueError(" ".join(p.bloqueios))
    backup = fazer_backup(pasta_backup, caminho_banco)
    with transacao(con):
        con.execute("DELETE FROM transacoes WHERE importacao_id = ?", (importacao_id,))
        con.execute("UPDATE conflitos SET situacao = 'importacao_excluida', decidido_por = ?, decidido_em = ?"
                    " WHERE importacao_id = ? AND situacao = 'pendente'", (usuario, agora(), importacao_id))
        con.execute("UPDATE importacoes SET excluida_em = ?, excluida_por = ?, backup_exclusao = ? WHERE id = ?",
                    (agora(), usuario, str(backup), importacao_id))
        registrar_auditoria(con, usuario, "importacao_excluida", json.dumps({
            "importacao_id": importacao_id, "arquivo": p.arquivo, "data_entrada": p.data_entrada,
            "registros_removidos": p.registros, "bruto_cent": p.bruto_cent, "liquido_cent": p.liquido_cent,
            "conflitos_descartados": p.conflitos_pendentes, "classificacoes_manuais_mantidas": p.classificacoes_manuais,
            "backup": str(backup)}, ensure_ascii=False))
    return p
