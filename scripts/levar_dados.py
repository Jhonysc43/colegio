"""Copia o banco atual para outro local (ex.: a pasta de rede) de forma segura.

Uso: python scripts/levar_dados.py <banco de origem> <banco de destino>

Usa a API de backup do SQLite (cópia consistente mesmo com o sistema aberto), grava o
destino como arquivo único (sem -wal/-shm) e confere a cópia. Recusa sobrescrever um
destino que já existe, para nunca apagar dados da pasta de rede por engano.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import banco  # noqa: E402


def main(origem: str, destino: str) -> int:
    o, d = Path(origem), Path(destino)
    if not o.is_file():
        print(f"Sem dados para levar: {o} não existe. A pasta de rede começará vazia.")
        return 0
    if d.exists():
        print(f"ERRO: já existe um banco em {d}. Nada foi alterado.", file=sys.stderr)
        return 1
    d.parent.mkdir(parents=True, exist_ok=True)
    src, dst = sqlite3.connect(o), sqlite3.connect(d)
    try:
        with dst:
            src.backup(dst)
        dst.execute("PRAGMA journal_mode = DELETE")
    finally:
        src.close()
        dst.close()
    n = banco.validar_backup(d)
    con = sqlite3.connect(d)
    ok = con.execute("PRAGMA quick_check").fetchone()[0]
    con.close()
    if ok != "ok":
        d.unlink()
        print(f"ERRO: a cópia não passou na verificação ({ok}). Nada foi levado.", file=sys.stderr)
        return 1
    print(f"Dados levados para {d}: {n} transações. Verificação: ok.")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
