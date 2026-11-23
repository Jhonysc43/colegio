"""Testes com a planilha de amostra (dados/amostra_ficticia.xlsx): mesma estrutura da planilha
real da intermediadora, com nomes, identificadores e valores fictícios (scripts/gerar_amostra_ficticia.py).

Executar:  python -m unittest discover -s tests -v
"""
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import openpyxl

from core import banco, classificacao
from core.formatos import formatar_brl, interpretar_data, para_centavos
from core.importacao import analisar_arquivo, confirmar_importacao
from core.indicadores import carregar_dataframe, resumo, resumo_por

RAIZ = Path(__file__).resolve().parent.parent
REFERENCIA = RAIZ / "dados" / "amostra_ficticia.xlsx"


class TestFormatos(unittest.TestCase):
    def test_centavos(self):
        self.assertEqual(para_centavos(96.95), 96_95)
        self.assertEqual(para_centavos(0.12), 12)
        self.assertEqual(para_centavos("1.234,56"), 123456)
        self.assertEqual(para_centavos("R$ 39.483,30"), 3948330)
        self.assertEqual(para_centavos(5516.2699999999995), 551627)
        self.assertIsNone(para_centavos(None))

    def test_brl(self):
        self.assertEqual(formatar_brl(123456789), "R$ 1.234.567,89")
        self.assertEqual(formatar_brl(12), "R$ 0,12")

    def test_datas(self):
        self.assertEqual(interpretar_data("06/11/2026 às 09:52")[0].strftime("%d/%m/%Y %H:%M"), "06/11/2026 09:52")
        dt, corrigida = interpretar_data("09T03:00:00.000Z/11/2026")
        self.assertEqual(dt.strftime("%d/%m/%Y"), "09/11/2026")
        self.assertTrue(corrigida)


class BaseBanco(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "teste.db"
        self.con = banco.conectar(self.db)
        banco.inicializar(self.con)
        classificacao.semear_regras(self.con)

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.tmp)

    def copia_modificada(self, alterar):
        destino = self.tmp / "modificada.xlsx"
        wb = openpyxl.load_workbook(REFERENCIA)
        alterar(wb.worksheets[0])
        wb.save(destino)
        return destino


class TestImportacaoReal(BaseBanco):
    def test_estrutura_identificada(self):
        a = analisar_arquivo(REFERENCIA)
        self.assertEqual(a.linha_cabecalho, 7)
        self.assertEqual(len(a.colunas), 28)
        self.assertIn("Sistemas", a.colunas)
        self.assertEqual(len(a.linhas), 203)
        self.assertEqual(len(a.linhas_ignoradas), 14)  # tabela dinâmica no rodapé
        self.assertEqual(a.data_liquidacao_sugerida, "2026-11-09")
        self.assertFalse(a.duplicadas_no_arquivo)

    def test_totais_batem_com_tabela_dinamica_da_planilha(self):
        a = analisar_arquivo(REFERENCIA)
        confirmar_importacao(self.con, a, "2026-11-09", "teste")
        df = carregar_dataframe(self.con)
        r = resumo(df)
        # Valores do "Total Geral" da tabela dinâmica da própria planilha
        self.assertEqual(r["bruto_cent"], 1544542)
        self.assertEqual(r["custo_cent"], 12338)
        self.assertEqual(r["liquido_cent"], 1532204)
        self.assertEqual(r["registros"], 203)
        self.assertEqual(r["pagamentos"], 161)  # ID Parcela distintos (split conta 1x)
        # Por Forma de Pagamento, os valores batem com a tabela dinâmica da planilha
        formas = resumo_por(df, "forma_pagamento").set_index("forma_pagamento")
        self.assertEqual(formas.loc["PIX", "bruto_cent"], 1027221)
        self.assertEqual(formas.loc["Boleto", "bruto_cent"], 517007)
        self.assertEqual(formas.loc["Crédito 1x", "bruto_cent"], 314)

    def test_valor_liquido_confere_em_todas_as_linhas(self):
        a = analisar_arquivo(REFERENCIA)
        self.assertFalse([x for x in a.alertas if x.tipo == "divergencia_liquido"])

    def test_dados_originais_preservados(self):
        a = analisar_arquivo(REFERENCIA)
        confirmar_importacao(self.con, a, "2026-11-09")
        linha = self.con.execute("SELECT dados_originais FROM transacoes WHERE linha_planilha = 8").fetchone()[0]
        d = json.loads(linha)
        self.assertEqual(len(d), 28)
        self.assertEqual(d["ID Parcela"], 900000001)
        self.assertEqual(d["Valor Bruto"], 123.22)
        self.assertEqual(d["Data de Liquidação"], "09T03:00:00.000Z/11/2026")  # texto original intacto

    def test_reimportacao_nao_duplica(self):
        a = analisar_arquivo(REFERENCIA)
        confirmar_importacao(self.con, a, "2026-11-09")
        r2 = confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.assertEqual((r2.inseridas, r2.ja_existentes, r2.conflitos), (0, 203, 0))
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0], 203)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM importacoes").fetchone()[0], 2)

    def test_registro_alterado_vira_conflito_sem_sobrescrever(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        mod = self.copia_modificada(lambda ws: ws.cell(row=8, column=9, value=100.00))
        r = confirmar_importacao(self.con, analisar_arquivo(mod), "2026-11-09")
        self.assertEqual(r.conflitos, 1)
        bruto = self.con.execute("SELECT valor_bruto_cent FROM transacoes WHERE linha_planilha = 8").fetchone()[0]
        self.assertEqual(bruto, 12322)  # original mantido

    def test_duplicada_no_arquivo_e_sinalizada(self):
        def duplicar(ws):
            for col in range(1, 29):
                ws.cell(row=212, column=col, value=ws.cell(row=8, column=col).value)
        a = analisar_arquivo(self.copia_modificada(duplicar))
        self.assertEqual(len(a.duplicadas_no_arquivo), 1)
        r = confirmar_importacao(self.con, a, "2026-11-09", duplicadas="manter_uma")
        self.assertEqual(r.inseridas, 203)

    def test_divergencia_de_liquido_e_sinalizada(self):
        mod = self.copia_modificada(lambda ws: ws.cell(row=8, column=11, value=90.00))
        a = analisar_arquivo(mod)
        self.assertEqual(len([x for x in a.alertas if x.tipo == "divergencia_liquido"]), 1)


class TestClassificacao(BaseBanco):
    def test_regras_iniciais_e_nao_identificado(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        df = carregar_dataframe(self.con)
        cats = df.groupby("categoria")["id_parcela"].nunique().to_dict()
        self.assertEqual(cats["BuscaTestamento"], 62)
        self.assertEqual(cats["Fatura quinzenal tabelião"], 44)
        self.assertEqual(cats["e-Not Assina"], 43)
        self.assertEqual(cats["e-Not Provas"], 3)          # prefixo ENPP começa com ENP
        self.assertEqual(cats["e-Not Certidões/AEV"], 9)   # regra DCR (versão 2)
        self.assertNotIn("Não identificado", cats)
        # A classificação coincide com a coluna "Sistemas" da planilha em todas as linhas
        self.assertTrue((df.categoria == df.sistemas_planilha).all())
        # CENSEC = BuscaTestamento
        self.assertEqual(set(df.loc[df.receita == "CENSEC", "categoria"]), {"BuscaTestamento"})

    def test_pedido_com_varios_numeros(self):
        regras = classificacao.carregar_regras(self.con)
        cat, _ = classificacao.classificar(regras, {"Nº do Pedido": "RAE000000101,RAE000000102"})
        self.assertEqual(cat, "e-Not Assina")
        cat, _ = classificacao.classificar(regras, {"Nº do Pedido": "RAE001,INV002"})
        self.assertEqual(cat, "Não identificado")

    def test_manual_prevalece_e_sobrevive_a_reimportacao(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        classificacao.definir_manual(self.con, "900000063", "e-Not Provas", "teste", "revisão")
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        df = carregar_dataframe(self.con)
        self.assertEqual(df.loc[df.id_parcela == "900000063", "categoria"].iloc[0], "e-Not Provas")
        self.assertEqual(df.loc[df.id_parcela == "900000063", "origem_classificacao"].iloc[0], "manual")


class TestAtualizacaoRegras(BaseBanco):
    def test_banco_antigo_recebe_regra_dcr_uma_unica_vez(self):
        con = banco.conectar(self.tmp / "antigo.db")
        banco.inicializar(con)
        for r in classificacao.REGRAS_INICIAIS:          # banco criado na versão 1 (sem config)
            classificacao._inserir_regra(con, *r)
        classificacao.semear_regras(con)
        dcr = "SELECT COUNT(*) FROM regras_classificacao WHERE valor = 'DCR'"
        self.assertEqual(con.execute(dcr).fetchone()[0], 1)
        con.execute("DELETE FROM regras_classificacao WHERE valor = 'DCR'")  # usuária apagou
        classificacao.semear_regras(con)
        self.assertEqual(con.execute(dcr).fetchone()[0], 0)                 # não volta sozinha
        con.close()


class TestIndicadores(BaseBanco):
    def setUp(self):
        super().setUp()
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.df = carregar_dataframe(self.con)

    def test_meio_boleto_hibrido_conta_como_boleto(self):
        from core.indicadores import meio_exibicao
        self.assertEqual(meio_exibicao("PIX", "Boleto Híbrido"), "Boleto")
        self.assertEqual(meio_exibicao("PIX", "Online"), "Pix")
        self.assertEqual(meio_exibicao("Crédito 1x", "Online"), "Cartão")
        m = resumo_por(self.df, "meio").set_index("meio")
        self.assertEqual(m.loc["Boleto", "pagamentos"], 65)
        self.assertEqual(m.loc["Boleto", "bruto_cent"], 957252)
        self.assertEqual(m.loc["Pix", "pagamentos"], 93)
        self.assertEqual(m.loc["Cartão", "pagamentos"], 3)
        self.assertEqual(m["bruto_cent"].sum(), 1544542)  # nada fica de fora

    def test_soma_das_receitas_igual_ao_total(self):
        r = resumo_por(self.df, "receita")
        self.assertEqual(r["bruto_cent"].sum(), 1544542)
        self.assertEqual(r["liquido_cent"].sum(), 1532204)
        self.assertEqual(r["pagamentos"].sum(), 161)  # cada pagamento pertence a uma receita

    def test_receita_diaria_e_boletos(self):
        from core.indicadores import boletos_por_dia, receita_diaria, totais_por_dia
        d = receita_diaria(self.df)
        self.assertEqual(d["bruto_cent"].sum(), 1544542)
        self.assertEqual((d["qtd_pix"] + d["qtd_cartao"] + d["qtd_boleto"]).sum(), 161)
        t = totais_por_dia(self.df)
        self.assertEqual(t.loc[0, "pagamentos"], 161)
        b = boletos_por_dia(self.df)
        self.assertEqual((b.loc[0, "pagamentos"], b.loc[0, "pagos_via_boleto"], b.loc[0, "pagos_via_pix"]), (65, 40, 25))

    def test_filtros_combinados(self):
        from core.indicadores import Filtros, aplicar_filtros
        f = aplicar_filtros(self.df, Filtros(receitas=["CENSEC"], meios=["Pix"]))
        self.assertEqual(f["id_parcela"].nunique(), 52)
        self.assertEqual(len(aplicar_filtros(self.df, Filtros(nr_pedido="RAE000000120"))), 2)
        self.assertEqual(len(aplicar_filtros(self.df, Filtros(entrada_ini="2026-11-10"))), 0)
        self.assertEqual(len(aplicar_filtros(self.df, Filtros(pagamento_ini="2026-11-07", pagamento_fim="2026-11-07"))), 30)
        self.assertEqual(len(aplicar_filtros(self.df, Filtros())), 203)


class TestBackup(BaseBanco):
    def test_backup_e_restauracao(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        arq = banco.fazer_backup(self.tmp / "bk", self.db)
        self.con.execute("DELETE FROM transacoes")
        self.con.close()
        banco.restaurar_backup(arq, self.db)
        self.con = banco.conectar(self.db)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0], 203)

    def test_falha_nao_grava_nada(self):
        a = analisar_arquivo(REFERENCIA)
        a.linhas[100].dados["ID do Lote"] = object()  # força erro no meio da gravação
        with self.assertRaises(Exception):
            confirmar_importacao(self.con, a, "2026-11-09")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0], 0)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM importacoes").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
