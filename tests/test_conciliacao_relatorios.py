"""Testes de conciliação, conflitos, regra de inclusão, configurações e relatórios."""
import io
import json

import openpyxl

from core import banco, classificacao, relatorios
from core.conciliacao import (conferencia_composicao, conflitos_pendentes, diferencas_conflito,
                              executar_verificacoes, resolver_conflito)
from core.importacao import analisar_arquivo, confirmar_importacao
from core.indicadores import aplicar_regra_inclusao, carregar_dataframe, definir_status_excluidos, resumo

from .test_importacao import REFERENCIA, BaseBanco


class BaseImportado(BaseBanco):
    def setUp(self):
        super().setUp()
        self.analise = analisar_arquivo(REFERENCIA)
        confirmar_importacao(self.con, self.analise, "2026-11-09")

    def df(self):
        return carregar_dataframe(self.con)

    def importar_modificada(self, alterar):
        r = confirmar_importacao(self.con, analisar_arquivo(self.copia_modificada(alterar)), "2026-11-09")
        return r


class TestVerificacoes(BaseImportado):
    def test_planilha_real(self):
        v = {x.codigo: x.quantidade for x in executar_verificacoes(self.con, self.df())}
        self.assertEqual(v["divergencia"], 0)
        self.assertEqual(v["sem_classificacao"], 0)
        self.assertEqual(v["classificacao_planilha"], 0)
        self.assertEqual(v["datas"], 0)
        self.assertEqual(v["pag_criacao"], 36)
        self.assertEqual(v["mesmo_pedido"], 12)

    def test_composicao_fecha(self):
        self.assertTrue(conferencia_composicao(self.df())["Confere"].all())

    def test_detecta_mesmo_pagamento_em_outra_data(self):
        pid = self.con.execute("SELECT id_parcela FROM transacoes WHERE linha_planilha = 128").fetchone()[0]
        self.con.execute("UPDATE transacoes SET data_entrada = '2026-11-10' WHERE linha_planilha = 128")
        v = {x.codigo: x for x in executar_verificacoes(self.con, self.df())}
        self.assertEqual(set(v["parcela_datas"].registros["id_parcela"]), {pid})


class TestConflitos(BaseImportado):
    def alterar(self, ws):
        ws.cell(row=8, column=9, value=100.00)

    def test_reimportar_nao_duplica_conflito(self):
        self.importar_modificada(self.alterar)
        self.importar_modificada(self.alterar)
        self.assertEqual(len(conflitos_pendentes(self.con)), 1)

    def test_diferencas_mostram_so_o_que_mudou(self):
        self.importar_modificada(self.alterar)
        c = conflitos_pendentes(self.con).iloc[0]
        d = diferencas_conflito(c["dados_atuais"], c["dados_novos"])
        self.assertEqual(d["Coluna"].tolist(), ["Valor Bruto"])

    def test_manter_original(self):
        self.importar_modificada(self.alterar)
        cid = int(conflitos_pendentes(self.con).iloc[0]["id"])
        resolver_conflito(self.con, cid, "mantido_original", "teste")
        self.assertEqual(resumo(self.df())["bruto_cent"], 1544542)
        self.assertTrue(conflitos_pendentes(self.con).empty)

    def test_substituir(self):
        self.importar_modificada(self.alterar)
        cid = int(conflitos_pendentes(self.con).iloc[0]["id"])
        resolver_conflito(self.con, cid, "substituido", "teste")
        df = self.df()
        self.assertEqual(len(df), 203)
        self.assertEqual(resumo(df)["bruto_cent"], 1544542 - 12322 + 10000)
        aud = self.con.execute("SELECT detalhes FROM auditoria WHERE acao = 'resolucao_conflito'").fetchone()[0]
        self.assertIn("123.22", json.loads(aud)["registro_anterior"])  # o original fica registrado

    def test_manter_ambos(self):
        self.importar_modificada(self.alterar)
        cid = int(conflitos_pendentes(self.con).iloc[0]["id"])
        resolver_conflito(self.con, cid, "ambos", "teste")
        df = self.df()
        self.assertEqual(len(df), 204)
        self.assertEqual(resumo(df)["pagamentos"], 161)  # mesmo ID Parcela: conta uma vez


class TestInclusao(BaseImportado):
    def test_status_excluido_sai_dos_indicadores_mas_fica_na_conciliacao(self):
        self.con.execute("UPDATE transacoes SET status_lote = 'Cancelado' WHERE linha_planilha = 8")
        definir_status_excluidos(self.con, ["Cancelado"], "teste")
        todos = self.df()
        ind = aplicar_regra_inclusao(todos, ["Cancelado"])
        self.assertEqual(len(ind), 202)
        self.assertEqual(resumo(ind)["bruto_cent"], 1544542 - 12322)
        v = {x.codigo: x.quantidade for x in executar_verificacoes(self.con, todos)}
        self.assertEqual(v["status"], 1)
        self.assertEqual(v["lote_status"], 203)  # o lote passou a ter dois status


class TestConfiguracoes(BaseImportado):
    def regras_atuais(self):
        return [dict(r) for r in self.con.execute(
            "SELECT campo, operador, valor, categoria, prioridade, ativa FROM regras_classificacao")]

    def test_salvar_regras_reclassifica(self):
        regras = [r for r in self.regras_atuais() if r["valor"] != "DCR"]
        self.assertEqual(classificacao.simular(regras, [json.loads(d) for d in self.df()["dados_originais"]])
                         .get("Não identificado"), 9)
        classificacao.salvar_regras(self.con, regras, "teste")
        self.assertEqual((self.df()["categoria"] == "Não identificado").sum(), 9)

    def test_regra_invalida_nao_salva(self):
        with self.assertRaises(ValueError):
            classificacao.salvar_regras(self.con, [{"campo": "Nº do Pedido", "operador": "comeca_com", "valor": "",
                                                    "categoria": "X", "prioridade": 1, "ativa": True}], "teste")
        self.assertEqual(len(self.regras_atuais()), 7)

    def test_grupos_e_manual(self):
        classificacao.salvar_grupos(self.con, {"BuscaTestamento": "CENSEC", "e-Not Provas": "e-Not"}, "teste")
        self.assertIn("e-Not", set(self.df()["receita"]))
        classificacao.definir_manual(self.con, "900000063", "e-Not Provas", "teste", "x")
        classificacao.remover_manual(self.con, "900000063", "teste")
        df = self.df()
        self.assertEqual(df.loc[df.id_parcela == "900000063", "categoria"].iloc[0], "e-Not Certidões/AEV")

    def test_backup_valido_e_invalido(self):
        arq = banco.fazer_backup(self.tmp / "bk", self.db)
        self.assertEqual(banco.validar_backup(arq), 203)
        falso = self.tmp / "falso.db"
        falso.write_bytes(b"isto nao e um banco")
        with self.assertRaises(ValueError):
            banco.validar_backup(falso)


class TestRelatorios(BaseImportado):
    def ler(self, tipo):
        rel = relatorios.montar(self.con, tipo, self.df(), "09/11/2026", "nenhum", self.analise.colunas)
        return rel, openpyxl.load_workbook(io.BytesIO(relatorios.gerar_excel(rel)))

    def test_todos_os_tipos_geram_excel_e_csv_com_periodo(self):
        for tipo in relatorios.TIPOS:
            rel, wb = self.ler(tipo)
            for ws in wb:
                self.assertEqual(ws["A2"].value, "Período: 09/11/2026")
            self.assertIn("Período: 09/11/2026", relatorios.gerar_csv(rel).decode("utf-8-sig"))

    def test_dados_preservam_originais(self):
        _, wb = self.ler("dados")
        ws = wb["Dados"]
        cab = [c.value for c in ws[6]]
        self.assertEqual(len(cab), 5 + 28)
        linha = dict(zip(cab, [c.value for c in ws[7]]))
        self.assertEqual(linha["Valor Bruto"], 123.22)
        self.assertEqual(linha["Data de Liquidação"], "09T03:00:00.000Z/11/2026")
        self.assertEqual(ws.max_row, 6 + 203)

    def test_totais_por_receita(self):
        _, wb = self.ler("receita")
        ws = wb["Por receita"]
        total = [r for r in ws.iter_rows(min_row=7, values_only=True) if r[0] == "TOTAL"][0]
        self.assertEqual(total[1], 161)
        self.assertAlmostEqual(total[3], 15445.42, places=2)
        self.assertEqual(ws.cell(row=7, column=4).number_format, relatorios.FORMATO_RS)

    def test_csv_padrao_brasileiro(self):
        rel = relatorios.montar(self.con, "mensal", self.df(), "09/11/2026", "nenhum")
        txt = relatorios.gerar_csv(rel).decode("utf-8-sig")
        self.assertIn("11/2026;161;203;15445,42;123,38;15322,04", txt)
