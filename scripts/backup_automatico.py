"""Backup automático do banco, para rodar todo dia pelo Agendador de Tarefas (Windows) ou cron/systemd (Linux).

Uso:
    python scripts/backup_automatico.py

Variáveis de ambiente:
    CLOUD_FINANCE_DB           caminho do banco (o mesmo usado pelo sistema)
    CLOUD_FINANCE_BACKUP_DIR   pasta dos backups automáticos (padrão: <pasta do banco>/backups/automaticos)
    CLOUD_FINANCE_BACKUP_DIAS  quantos dias de backups manter (padrão: 30; os 7 mais recentes sempre ficam)

Termina com código 0 se deu certo e 1 se falhou (o agendador pode alertar a TI).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import banco  # noqa: E402

MANTER_SEMPRE = 7


def main() -> int:
    origem = banco.caminho_banco()
    if not origem.exists():
        print(f"ERRO: banco não encontrado em {origem}", file=sys.stderr)
        return 1
    pasta = banco.pasta_backups_automaticos(origem)
    try:
        dias = int(os.environ.get("CLOUD_FINANCE_BACKUP_DIAS", "30"))
    except ValueError:
        dias = 30
    try:
        arq = banco.fazer_backup(pasta, origem)
        n = banco.validar_backup(arq)
    except Exception as e:  # noqa: BLE001
        print(f"ERRO: backup falhou: {e}", file=sys.stderr)
        return 1
    print(f"Backup criado: {arq} ({n} transações, {arq.stat().st_size / 1024:.0f} KB)")
    for antigo in banco.limpar_backups(pasta, dias, MANTER_SEMPRE):
        print(f"Removido backup antigo: {antigo.name}")
    con = banco.conectar(origem)
    try:
        banco.registrar_auditoria(con, "sistema", "backup", f"automático: {arq}")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
