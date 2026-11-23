"""Testes da exclusão de importação."""
import sqlite3

from core import banco, classificacao
from core.conciliacao import conflitos_pendentes, resolver_conflito
from core.importacao import (analisar_arquivo, arquivo_ja_importado, confirmar_importacao, excluir_importacao,
                             previa_exclusao)
from core.indicadores import carregar_dataframe, resumo

from .test_importacao import REFERENCIA, BaseBanco


class TestExclusao(BaseBanco):
    def excluir(self, imp_id):
        return excluir_importacao(self.con, imp_id, "teste", self.db, self.tmp / "bk")

    def test_exclui_e_permite_reimportar(self):
        r = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        p = previa_exclusao(self.con, r.importacao_id)
        self.assertEqual((p.registros, p.pagamentos, p.bruto_cent), (203, 161, 1544542))
        self.excluir(r.importacao_id)
        self.assertTrue(carregar_dataframe(self.con).empty)
        imp = self.con.execute("SELECT excluida_em, excluida_por, backup_exclusao FROM importacoes").fetchone()
        self.assertIsNotNone(imp["excluida_em"])
        self.assertEqual(imp["excluida_por"], "teste")
        self.assertEqual(banco.validar_backup(imp["backup_exclusao"]), 203)  # backup tem os dados
        self.assertEqual(arquivo_ja_importado(self.con, analisar_arquivo(REFERENCIA).hash_arquivo), [])
        r2 = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.assertEqual(r2.inseridas, 203)
        aud = self.con.execute("SELECT COUNT(*) FROM auditoria WHERE acao = 'importacao_excluida'").fetchone()[0]
        self.assertEqual(aud, 1)

    def test_data_errada_corrigida(self):
        """Caso típico: importou com data de entrada errada, exclui e importa com a certa."""
        r = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-19")
        self.excluir(r.importacao_id)
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.assertEqual(set(carregar_dataframe(self.con)["data_entrada"]), {"2026-11-09"})

    def test_nao_remove_registros_de_outra_importacao(self):
        r1 = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        r2 = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")  # tudo já existente
        p = previa_exclusao(self.con, r2.importacao_id)
        self.assertEqual((p.registros, p.ja_existentes), (0, 203))
        self.excluir(r2.importacao_id)
        self.assertEqual(resumo(carregar_dataframe(self.con))["bruto_cent"], 1544542)

    def test_nao_exclui_duas_vezes(self):
        r = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.excluir(r.importacao_id)
        with self.assertRaises(ValueError):
            self.excluir(r.importacao_id)

    def test_classificacao_manual_e_mantida(self):
        r = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        classificacao.definir_manual(self.con, "900000063", "e-Not Provas", "teste", "x")
        self.assertEqual(previa_exclusao(self.con, r.importacao_id).classificacoes_manuais, ["900000063"])
        self.excluir(r.importacao_id)
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        df = carregar_dataframe(self.con)
        self.assertEqual(df.loc[df.id_parcela == "900000063", "categoria"].iloc[0], "e-Not Provas")

    def test_conflito_pendente_e_descartado(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        mod = self.copia_modificada(lambda ws: ws.cell(row=8, column=9, value=100.00))
        r2 = confirmar_importacao(self.con, analisar_arquivo(mod), "2026-11-09")
        self.assertEqual(previa_exclusao(self.con, r2.importacao_id).conflitos_pendentes, 1)
        self.excluir(r2.importacao_id)
        self.assertTrue(conflitos_pendentes(self.con).empty)
        self.assertEqual(resumo(carregar_dataframe(self.con))["bruto_cent"], 1544542)

    def test_bloqueia_quando_conflito_foi_substituido(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        mod = self.copia_modificada(lambda ws: ws.cell(row=8, column=9, value=100.00))
        r2 = confirmar_importacao(self.con, analisar_arquivo(mod), "2026-11-09")
        resolver_conflito(self.con, int(conflitos_pendentes(self.con).iloc[0]["id"]), "substituido", "teste")
        p = previa_exclusao(self.con, r2.importacao_id)
        self.assertTrue(p.bloqueios)
        with self.assertRaises(ValueError):
            self.excluir(r2.importacao_id)
        self.assertEqual(len(carregar_dataframe(self.con)), 203)  # nada foi apagado

    def test_historico_com_importacoes_ativas_e_excluidas(self):
        """Erro relatado em 17/11/2026: histórico misturando importação excluída e ativa (pandas 3)."""
        import pandas as pd
        r = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-19")
        self.excluir(r.importacao_id)
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        df = pd.DataFrame([dict(l) for l in self.con.execute("SELECT excluida_em, excluida_por FROM importacoes")])
        ativas = [e for e in df["excluida_em"] if not pd.notna(e)]
        self.assertEqual(len(ativas), 1)

    def test_conflito_pendente_apos_excluir_importacao_original(self):
        r1 = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        mod = self.copia_modificada(lambda ws: ws.cell(row=8, column=9, value=100.00))
        confirmar_importacao(self.con, analisar_arquivo(mod), "2026-11-09")
        self.excluir(r1.importacao_id)
        c = conflitos_pendentes(self.con).iloc[0]
        from core.conciliacao import diferencas_conflito
        self.assertIn("Valor Bruto", diferencas_conflito(c["dados_atuais"], c["dados_novos"])["Coluna"].tolist())
        resolver_conflito(self.con, int(c["id"]), "substituido", "teste")
        self.assertEqual(resumo(carregar_dataframe(self.con))["bruto_cent"], 10000)

    def test_migracao_de_banco_antigo(self):
        antigo = self.tmp / "antigo.db"
        con = sqlite3.connect(antigo)
        con.execute("CREATE TABLE importacoes (id INTEGER PRIMARY KEY, arquivo TEXT)")  # sem colunas novas
        con.commit()
        con.close()
        con = banco.conectar(antigo)
        banco.inicializar(con)
        cols = {r[1] for r in con.execute("PRAGMA table_info(importacoes)")}
        self.assertTrue({"excluida_em", "excluida_por", "backup_exclusao"} <= cols)
        con.close()
