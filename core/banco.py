"""Banco de dados persistente (SQLite).

O caminho do banco vem da variável de ambiente CLOUD_FINANCE_DB
(padrão: dados/cloud_finance.db).

Dois modos, escolhidos sozinhos pelo caminho do banco (ou por CLOUD_FINANCE_MODO=rede|local):
- local: disco do próprio computador ou servidor -> journal WAL (rápido, leituras não bloqueiam).
- rede: pasta compartilhada (ex.: Z:) usada por vários computadores -> journal DELETE (o WAL não
  funciona em rede) + tranca de gravação em arquivo (core/trava.py).
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from .marca import NOME_SISTEMA, PREFIXO_ARQUIVOS
from .trava import trava_gravacao

RAIZ = Path(__file__).resolve().parent.parent
CAMINHO_PADRAO = RAIZ / "dados" / "cloud_finance.db"

ESQUEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS importacoes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo               TEXT NOT NULL,
    hash_arquivo          TEXT NOT NULL,
    aba                   TEXT,
    data_entrada          TEXT NOT NULL,          -- informada pelo usuário (AAAA-MM-DD)
    processado_em         TEXT NOT NULL,
    usuario               TEXT,
    linhas_lidas          INTEGER NOT NULL,
    linhas_inseridas      INTEGER NOT NULL,
    linhas_ja_existentes  INTEGER NOT NULL,
    linhas_conflito       INTEGER NOT NULL,
    linhas_ignoradas      INTEGER NOT NULL,       -- resumo/tabela dinâmica, vazias
    alertas               INTEGER NOT NULL,
    colunas               TEXT NOT NULL,          -- JSON: colunas originais na ordem
    resultado             TEXT NOT NULL           -- 'concluida' | 'concluida_com_alertas'
);

CREATE TABLE IF NOT EXISTS transacoes (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    importacao_id         INTEGER NOT NULL REFERENCES importacoes(id),
    linha_planilha        INTEGER NOT NULL,
    chave_registro        TEXT NOT NULL UNIQUE,   -- 'venda:<ID da Venda>' ou 'hash:<sha>'
    hash_conteudo         TEXT NOT NULL,
    id_parcela            TEXT,
    id_lote               TEXT,
    id_venda              TEXT,
    status_lote           TEXT,
    nr_pedido             TEXT,
    forma_pagamento       TEXT,
    meio_pagamento        TEXT,
    valor_bruto_cent      INTEGER,
    custo_financeiro_cent INTEGER,
    valor_liquido_cent    INTEGER,
    data_criacao          TEXT,
    data_pagamento        TEXT,
    data_liquidacao       TEXT,                   -- interpretada da planilha
    data_entrada          TEXT NOT NULL,          -- informada na importação
    estabelecimento       TEXT,
    sistemas_planilha     TEXT,                   -- valor da coluna "Sistemas" (fórmula do Excel)
    dados_originais       TEXT NOT NULL           -- JSON com TODAS as colunas, sem alteração
);
CREATE INDEX IF NOT EXISTS ix_tr_parcela ON transacoes(id_parcela);
CREATE INDEX IF NOT EXISTS ix_tr_lote    ON transacoes(id_lote);
CREATE INDEX IF NOT EXISTS ix_tr_pedido  ON transacoes(nr_pedido);
CREATE INDEX IF NOT EXISTS ix_tr_entrada ON transacoes(data_entrada);

-- Linhas que chegaram com a mesma chave de um registro existente mas com
-- conteúdo diferente. Nunca sobrescrevem o original: aguardam decisão.
CREATE TABLE IF NOT EXISTS conflitos (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    importacao_id     INTEGER NOT NULL REFERENCES importacoes(id),
    chave_registro    TEXT NOT NULL,
    linha_planilha    INTEGER NOT NULL,
    dados_originais   TEXT NOT NULL,
    situacao          TEXT NOT NULL DEFAULT 'pendente',  -- pendente | mantido_original | substituido | ambos
    decidido_por      TEXT,
    decidido_em       TEXT
);

CREATE TABLE IF NOT EXISTS alertas_importacao (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    importacao_id  INTEGER NOT NULL REFERENCES importacoes(id),
    linha_planilha INTEGER,
    coluna         TEXT,
    tipo           TEXT NOT NULL,
    mensagem       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS regras_classificacao (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    campo      TEXT NOT NULL,     -- coluna original da planilha (ex.: 'Nº do Pedido')
    operador   TEXT NOT NULL,     -- 'comeca_com' | 'contem' | 'igual'
    valor      TEXT NOT NULL,
    categoria  TEXT NOT NULL,
    prioridade INTEGER NOT NULL DEFAULT 100,  -- menor = avaliada primeiro
    ativa      INTEGER NOT NULL DEFAULT 1,
    criada_em  TEXT NOT NULL
);

-- Classificação manual vale por ID Parcela e é preservada em novas importações.
CREATE TABLE IF NOT EXISTS classificacoes_manuais (
    id_parcela  TEXT PRIMARY KEY,
    categoria   TEXT NOT NULL,
    usuario     TEXT,
    motivo      TEXT,
    definida_em TEXT NOT NULL
);

-- Agrupamento de categorias em "receitas" para os indicadores
-- (ex.: CENSEC = BuscaTestamento). Categoria sem grupo aparece com o próprio nome.
CREATE TABLE IF NOT EXISTS grupos_receita (
    categoria TEXT PRIMARY KEY,
    grupo     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS configuracoes (
    chave TEXT PRIMARY KEY,
    valor TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS usuarios (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    login             TEXT NOT NULL UNIQUE,
    nome              TEXT NOT NULL,
    email             TEXT,
    perfil            TEXT NOT NULL,          -- administrador | operador | consulta
    senha_hash        TEXT NOT NULL,          -- scrypt + sal; a senha nunca é guardada
    ativo             INTEGER NOT NULL DEFAULT 1,
    trocar_senha      INTEGER NOT NULL DEFAULT 1,
    criado_em         TEXT NOT NULL,
    ultimo_acesso     TEXT,
    tentativas_falhas INTEGER NOT NULL DEFAULT 0,
    bloqueado_ate     TEXT
);

CREATE TABLE IF NOT EXISTS auditoria (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    momento   TEXT NOT NULL,
    usuario   TEXT,
    acao      TEXT NOT NULL,
    detalhes  TEXT
);
"""


def caminho_banco() -> Path:
    return Path(os.environ.get("CLOUD_FINANCE_DB", CAMINHO_PADRAO))


def em_rede(caminho: Path | str) -> bool:
    """O banco está numa pasta de rede? (unidade mapeada como Z:, ou caminho \\\\servidor\\pasta)"""
    modo = os.environ.get("CLOUD_FINANCE_MODO", "").strip().lower()
    if modo in ("rede", "local"):
        return modo == "rede"
    texto = str(caminho)
    if texto.startswith(("\\\\", "//")):
        return True
    if sys.platform == "win32":
        try:
            import ctypes
            raiz = os.path.splitdrive(os.path.abspath(texto))[0] + "\\"
            return ctypes.windll.kernel32.GetDriveTypeW(raiz) == 4  # DRIVE_REMOTE
        except Exception:  # noqa: BLE001
            return False
    return False


class Conexao(sqlite3.Connection):
    """Conexão que sabe onde está o banco e se ele está em rede."""
    caminho: Path
    rede: bool = False
    bloquear_gravacao: str | None = None   # motivo, se o arquivo apresentou problema


def conectar(caminho: Path | str | None = None) -> Conexao:
    caminho = Path(caminho) if caminho else caminho_banco()
    caminho.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None: transações explícitas via transacao(). timeout: espera até 30 s
    # se outra sessão estiver gravando, em vez de falhar.
    con = sqlite3.connect(caminho, isolation_level=None, check_same_thread=False, timeout=30, factory=Conexao)
    con.caminho = caminho
    con.rede = em_rede(caminho)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 30000")
    if con.rede:
        con.execute("PRAGMA journal_mode = DELETE")  # WAL não funciona em pasta de rede
        con.execute("PRAGMA synchronous = FULL")
    else:
        con.execute("PRAGMA journal_mode = WAL")     # leituras não bloqueiam gravações
    return con


def inicializar(con: sqlite3.Connection) -> None:
    """Cria as tabelas que faltam e aplica migrações de colunas (CREATE IF NOT EXISTS)."""
    if getattr(con, "rede", False):
        with trava_gravacao(con.caminho, "inicialização"):
            _inicializar(con)
    else:
        _inicializar(con)


def _inicializar(con) -> None:
    con.executescript(ESQUEMA)
    # Migrações de bancos criados em versões anteriores (colunas novas).
    cols = {r[1] for r in con.execute("PRAGMA table_info(importacoes)")}
    for nome in ("excluida_em", "excluida_por", "backup_exclusao"):
        if nome not in cols:
            con.execute(f"ALTER TABLE importacoes ADD COLUMN {nome} TEXT")
    con.commit()


@contextmanager
def transacao(con: sqlite3.Connection):
    """Tudo ou nada: se qualquer passo falhar, nada é gravado."""
    motivo = getattr(con, "bloquear_gravacao", None)
    if motivo:
        raise RuntimeError(f"Gravação bloqueada: {motivo}")
    if getattr(con, "rede", False):
        with trava_gravacao(con.caminho):
            with _transacao_sqlite(con):
                yield con
    else:
        with _transacao_sqlite(con):
            yield con


@contextmanager
def _transacao_sqlite(con):
    # IMMEDIATE: reserva a gravação já no início; outra sessão que também queira gravar
    # espera a vez (busy_timeout) em vez de colidir no meio da transação.
    con.execute("BEGIN IMMEDIATE")
    try:
        yield con
        con.execute("COMMIT")
    except BaseException:
        con.execute("ROLLBACK")
        raise


def ler_config(con, chave: str, padrao: str | None = None) -> str | None:
    r = con.execute("SELECT valor FROM configuracoes WHERE chave = ?", (chave,)).fetchone()
    return r[0] if r else padrao


def gravar_config(con, chave: str, valor: str) -> None:
    con.execute("INSERT INTO configuracoes (chave, valor) VALUES (?,?)"
                " ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor", (chave, valor))


def agora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def registrar_auditoria(con, usuario: str | None, acao: str, detalhes: str = "") -> None:
    con.execute(
        "INSERT INTO auditoria (momento, usuario, acao, detalhes) VALUES (?,?,?,?)",
        (agora(), usuario, acao, detalhes),
    )


def fazer_backup(destino_dir: Path | str | None = None, caminho: Path | str | None = None) -> Path:
    """Cópia consistente do banco (API de backup do SQLite, segura com o app aberto)."""
    origem = Path(caminho) if caminho else caminho_banco()
    destino_dir = Path(destino_dir) if destino_dir else origem.parent / "backups"
    destino_dir.mkdir(parents=True, exist_ok=True)
    base = f"{PREFIXO_ARQUIVOS}_{datetime.now():%Y%m%d_%H%M%S}"
    destino, n = destino_dir / f"{base}.db", 2
    while destino.exists():  # dois backups no mesmo segundo nunca se sobrescrevem
        destino, n = destino_dir / f"{base}_{n}.db", n + 1
    src = sqlite3.connect(origem)
    dst = sqlite3.connect(destino)
    with dst:
        src.backup(dst)
    dst.execute("PRAGMA journal_mode = DELETE")  # backup = um arquivo único, sem -wal/-shm
    src.close()
    dst.close()
    return destino


def validar_backup(arquivo: Path | str) -> int:
    """Confere se o arquivo é um banco do sistema; retorna a quantidade de transações."""
    if not Path(arquivo).is_file():
        raise ValueError("Arquivo de backup não encontrado.")
    con = sqlite3.connect(arquivo)  # caminho simples: funciona também em \\servidor\pasta
    try:
        n = con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0]
        con.execute("SELECT COUNT(*) FROM importacoes").fetchone()
        return n
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"O arquivo não é um backup válido do {NOME_SISTEMA}.") from exc
    finally:
        con.close()


def restaurar_backup(arquivo_backup: Path | str, caminho: Path | str | None = None) -> Path:
    """Restaura um backup. Antes, guarda uma cópia do banco atual (mesmo que ele esteja danificado)."""
    alvo = Path(caminho) if caminho else caminho_banco()
    validar_backup(arquivo_backup)
    if alvo.exists():
        pasta = alvo.parent / "backups" / "antes_de_restaurar"
        try:
            fazer_backup(pasta, alvo)
        except sqlite3.DatabaseError:
            # banco danificado: a cópia pelo SQLite falha, então copia o arquivo como está
            import shutil
            pasta.mkdir(parents=True, exist_ok=True)
            shutil.copy2(alvo, pasta / f"{PREFIXO_ARQUIVOS}_danificado_{datetime.now():%Y%m%d_%H%M%S}.db")

    def copiar():
        src = sqlite3.connect(arquivo_backup)
        try:
            dst = sqlite3.connect(alvo, timeout=30)
            try:
                with dst:
                    src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

    try:
        if em_rede(alvo):
            with trava_gravacao(alvo, "restauração de backup"):
                copiar()
        else:
            copiar()
    except sqlite3.DatabaseError:
        # o arquivo atual está danificado a ponto de o SQLite não abrir: substitui o arquivo inteiro
        import shutil
        for extra in (Path(f"{alvo}-wal"), Path(f"{alvo}-shm"), Path(f"{alvo}-journal")):
            if extra.exists():
                extra.unlink()
        shutil.copy2(arquivo_backup, alvo)
    return alvo


def verificar_integridade(con) -> str:
    """'ok' se o arquivo do banco está íntegro; senão, a descrição do problema."""
    try:
        linhas = [r[0] for r in con.execute("PRAGMA quick_check").fetchall()]
    except sqlite3.DatabaseError as e:
        return str(e)
    return "ok" if linhas == ["ok"] else "; ".join(linhas[:5])


def pasta_backups_automaticos(caminho: Path | str | None = None) -> Path:
    origem = Path(caminho) if caminho else caminho_banco()
    return Path(os.environ.get("CLOUD_FINANCE_BACKUP_DIR", origem.parent / "backups" / "automaticos"))


def limpar_backups(pasta: Path, dias: int = 30, manter: int = 7) -> list[Path]:
    """Apaga backups com mais de `dias`, mas nunca os `manter` mais recentes."""
    backups = sorted(pasta.glob(f"{PREFIXO_ARQUIVOS}_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    limite = time.time() - dias * 86400
    removidos = []
    for antigo in backups[manter:]:
        if antigo.stat().st_mtime < limite:
            antigo.unlink()
            removidos.append(antigo)
    return removidos


def backup_diario_se_preciso(caminho: Path | str | None = None, horas: float = 20) -> Path | None:
    """Faz o backup automático se o último tiver mais de `horas`. Usado na abertura do sistema,
    quando não há servidor para agendar. Retorna o arquivo criado, ou None se não precisou."""
    origem = Path(caminho) if caminho else caminho_banco()
    if not origem.exists():
        return None
    pasta = pasta_backups_automaticos(origem)
    pasta.mkdir(parents=True, exist_ok=True)

    def recente() -> bool:
        return any(time.time() - p.stat().st_mtime < horas * 3600
                   for p in pasta.glob(f"{PREFIXO_ARQUIVOS}_*.db"))

    if recente():
        return None
    # a tranca evita que dois computadores abrindo juntos façam dois backups
    with trava_gravacao(origem, "backup automático", espera_max=60):
        if recente():
            return None
        arq = fazer_backup(pasta, origem)
    validar_backup(arq)
    try:
        dias = int(os.environ.get("CLOUD_FINANCE_BACKUP_DIAS", "30"))
    except ValueError:
        dias = 30
    limpar_backups(pasta, dias)
    return arq
