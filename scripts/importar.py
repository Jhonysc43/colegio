"""Importação pela linha de comando (útil para testes e cargas em lote).

Uso:
    python scripts/importar.py caminho/arquivo.xlsx --data-entrada 09/11/2026 [--confirmar]

Sem --confirmar, apenas mostra a prévia (nada é gravado).
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import banco, classificacao  # noqa: E402
from core.formatos import formatar_brl, formatar_data  # noqa: E402
from core.importacao import analisar_arquivo, arquivo_ja_importado, confirmar_importacao  # noqa: E402
from core.indicadores import carregar_dataframe, resumo, resumo_por  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arquivo")
    ap.add_argument("--data-entrada", required=True, help="DD/MM/AAAA")
    ap.add_argument("--aba")
    ap.add_argument("--confirmar", action="store_true")
    ap.add_argument("--usuario", default="cli")
    args = ap.parse_args()

    data_entrada = datetime.strptime(args.data_entrada, "%d/%m/%Y").date().isoformat()
    a = analisar_arquivo(args.arquivo, aba=args.aba)
    t = a.totais()
    print(f"Arquivo: {a.arquivo} | aba: {a.aba} | cabeçalho na linha {a.linha_cabecalho}")
    print(f"Colunas ({len(a.colunas)}): {', '.join(a.colunas)}")
    print(f"Registros: {t['registros']} | Pagamentos: {t['pagamentos (ID Parcela distintos)']}")
    print(f"Bruto {formatar_brl(t['bruto_cent'])} | Custo {formatar_brl(t['custo_cent'])} | "
          f"Líquido {formatar_brl(t['liquido_cent'])}")
    print(f"Linhas ignoradas: {len(a.linhas_ignoradas)} | vazias: {a.linhas_vazias}")
    if a.data_liquidacao_sugerida:
        print(f"Data de liquidação na planilha: {formatar_data(a.data_liquidacao_sugerida)}")
    for tipo, col, qtd, ex in a.alertas_agrupados():
        print(f"  ALERTA {tipo} [{col}]: {qtd} linha(s), ex.: {ex[:5]}")

    if not args.confirmar:
        print("\nPrévia apenas. Use --confirmar para gravar.")
        return
    con = banco.conectar()
    banco.inicializar(con)
    classificacao.semear_regras(con)
    anteriores = arquivo_ja_importado(con, a.hash_arquivo)
    if anteriores:
        print(f"Aviso: este mesmo arquivo já foi importado {len(anteriores)} vez(es). "
              "Registros existentes não serão duplicados.")
    r = confirmar_importacao(con, a, data_entrada, args.usuario)
    print(f"\nImportação #{r.importacao_id}: inseridas {r.inseridas}, já existentes {r.ja_existentes}, "
          f"conflitos {r.conflitos}")
    df = carregar_dataframe(con)
    print("Total no banco:", {k: (formatar_brl(v) if k.endswith('_cent') else v) for k, v in resumo(df).items()})
    for col in ("categoria", "meio"):
        print(resumo_por(df, col).to_string(index=False))


if __name__ == "__main__":
    main()
