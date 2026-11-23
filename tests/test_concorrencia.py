"""Vários usuários ao mesmo tempo, cada um com a sua conexão (como no servidor)."""
import threading

from core import banco, classificacao
from core.importacao import analisar_arquivo, confirmar_importacao
from core.indicadores import carregar_dataframe, resumo

from .test_importacao import REFERENCIA, BaseBanco


class TestConcorrencia(BaseBanco):
    def test_importacoes_e_leituras_simultaneas(self):
        analise = analisar_arquivo(REFERENCIA)
        erros, leituras = [], []

        def importar():
            con = banco.conectar(self.db)
            try:
                confirmar_importacao(con, analise, "2026-11-09", "usuario")
            except Exception as e:  # noqa: BLE001
                erros.append(repr(e))
            finally:
                con.close()

        def ler():
            con = banco.conectar(self.db)
            try:
                for _ in range(5):
                    leituras.append(len(carregar_dataframe(con)))
            except Exception as e:  # noqa: BLE001
                erros.append(repr(e))
            finally:
                con.close()

        def classificar():
            con = banco.conectar(self.db)
            try:
                for i in range(10):
                    classificacao.definir_manual(con, f"teste{i}", "e-Not Provas", "usuario", "x")
            except Exception as e:  # noqa: BLE001
                erros.append(repr(e))
            finally:
                con.close()

        threads = ([threading.Thread(target=importar) for _ in range(4)]
                   + [threading.Thread(target=ler) for _ in range(4)]
                   + [threading.Thread(target=classificar) for _ in range(2)])
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=120)
        self.assertEqual(erros, [])
        df = carregar_dataframe(self.con)
        self.assertEqual(len(df), 203)                       # 4 importações do mesmo arquivo, sem duplicar
        self.assertEqual(resumo(df)["bruto_cent"], 1544542)
        imp = self.con.execute("SELECT SUM(linhas_inseridas), SUM(linhas_ja_existentes) FROM importacoes").fetchone()
        self.assertEqual(tuple(imp), (203, 3 * 203))
        self.assertTrue(all(n in (0, 203) for n in leituras))  # nenhuma leitura vê importação pela metade
