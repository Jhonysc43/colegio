"""Modo pasta de rede: tranca de gravação, journal, vários processos, integridade, backup diário."""
import multiprocessing as mp
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from core import banco, classificacao
from core.importacao import analisar_arquivo, confirmar_importacao
from core.indicadores import carregar_dataframe, resumo
from core.trava import TravaOcupada, caminho_trava, trava_gravacao

from .test_importacao import REFERENCIA


def _processo_trabalho(db: str, ref: str, n: int, fila) -> None:
    """Simula um computador: importa a planilha e grava classificações manuais."""
    os.environ["CLOUD_FINANCE_MODO"] = "rede"
    try:
        con = banco.conectar(db)
        confirmar_importacao(con, analisar_arquivo(ref), "2026-11-09", f"pc{n}")
        for i in range(5):
            classificacao.definir_manual(con, f"p{n}-{i}", "e-Not Provas", f"pc{n}", "teste")
        con.close()
        fila.put("ok")
    except Exception as e:  # noqa: BLE001
        fila.put(repr(e))


class BaseRede(unittest.TestCase):
    def setUp(self):
        self.antes = os.environ.get("CLOUD_FINANCE_MODO")
        os.environ["CLOUD_FINANCE_MODO"] = "rede"
        self.tmp = Path(tempfile.mkdtemp())
        self.db = self.tmp / "cloud_finance.db"
        self.con = banco.conectar(self.db)
        banco.inicializar(self.con)
        classificacao.semear_regras(self.con)

    def tearDown(self):
        self.con.close()
        if self.antes is None:
            os.environ.pop("CLOUD_FINANCE_MODO", None)
        else:
            os.environ["CLOUD_FINANCE_MODO"] = self.antes
        shutil.rmtree(self.tmp)


class TestTrava(BaseRede):
    def test_exclusiva_e_liberada(self):
        with trava_gravacao(self.db, "a"):
            self.assertTrue(caminho_trava(self.db).exists())
            with self.assertRaises(TravaOcupada):
                with trava_gravacao(self.db, "b", espera_max=0.5):
                    pass
        self.assertFalse(caminho_trava(self.db).exists())

    def test_liberada_mesmo_com_erro(self):
        with self.assertRaises(ZeroDivisionError):
            with trava_gravacao(self.db):
                1 / 0
        self.assertFalse(caminho_trava(self.db).exists())

    def test_segundo_espera_a_vez(self):
        ordem = []

        def segundo():
            with trava_gravacao(self.db, "b", espera_max=5):
                ordem.append("b")

        with trava_gravacao(self.db, "a"):
            t = threading.Thread(target=segundo)
            t.start()
            time.sleep(0.5)
            ordem.append("a")
        t.join()
        self.assertEqual(ordem, ["a", "b"])

    def test_trava_abandonada_e_removida(self):
        caminho_trava(self.db).write_text("{}")
        velho = time.time() - 3600
        os.utime(caminho_trava(self.db), (velho, velho))
        with trava_gravacao(self.db, espera_max=1):
            pass
        self.assertFalse(caminho_trava(self.db).exists())


class TestModoRede(BaseRede):
    def test_journal_delete_e_trava_na_transacao(self):
        self.assertTrue(self.con.rede)
        self.assertEqual(self.con.execute("PRAGMA journal_mode").fetchone()[0], "delete")
        with banco.transacao(self.con):
            self.assertTrue(caminho_trava(self.db).exists())
        self.assertFalse(caminho_trava(self.db).exists())

    def test_modo_local_continua_wal(self):
        os.environ["CLOUD_FINANCE_MODO"] = "local"
        con = banco.conectar(self.tmp / "local.db")
        self.assertFalse(con.rede)
        self.assertEqual(con.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        con.close()

    def test_varios_computadores_ao_mesmo_tempo(self):
        ctx = mp.get_context("spawn")
        fila = ctx.Queue()
        procs = [ctx.Process(target=_processo_trabalho, args=(str(self.db), str(REFERENCIA), n, fila))
                 for n in range(4)]
        for p in procs:
            p.start()
        resultados = [fila.get(timeout=180) for _ in procs]
        for p in procs:
            p.join(timeout=30)
        self.assertEqual(resultados, ["ok"] * 4)
        df = carregar_dataframe(self.con)
        self.assertEqual(len(df), 203)                         # nada duplicado
        self.assertEqual(resumo(df)["bruto_cent"], 1544542)
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM classificacoes_manuais").fetchone()[0], 20)
        self.assertEqual(banco.verificar_integridade(self.con), "ok")
        self.assertFalse(caminho_trava(self.db).exists())

    def test_gravacao_bloqueada_quando_arquivo_tem_problema(self):
        self.con.bloquear_gravacao = "arquivo com problema"
        with self.assertRaises(RuntimeError):
            confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.assertEqual(self.con.execute("SELECT COUNT(*) FROM transacoes").fetchone()[0], 0)


class TestIntegridadeEBackupDiario(BaseRede):
    def test_detecta_arquivo_corrompido(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        self.assertEqual(banco.verificar_integridade(self.con), "ok")
        copia = self.tmp / "corrompido.db"
        shutil.copy(self.db, copia)
        with open(copia, "r+b") as f:
            f.seek(8192)
            f.write(os.urandom(16384))
        con = banco.conectar(copia)
        self.assertNotEqual(banco.verificar_integridade(con), "ok")
        con.close()

    def test_backup_uma_vez_por_dia(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        primeiro = banco.backup_diario_se_preciso(self.db)
        self.assertIsNotNone(primeiro)
        self.assertEqual(banco.validar_backup(primeiro), 203)
        self.assertIsNone(banco.backup_diario_se_preciso(self.db))   # já fez hoje
        ontem = time.time() - 25 * 3600
        os.utime(primeiro, (ontem, ontem))
        segundo = banco.backup_diario_se_preciso(self.db)
        self.assertIsNotNone(segundo)
        self.assertEqual(len(list(banco.pasta_backups_automaticos(self.db).glob("*.db"))), 2)


if __name__ == "__main__":
    unittest.main()


class TestRestauracaoDeArquivoDanificado(BaseRede):
    def test_restaura_mesmo_com_banco_atual_corrompido(self):
        confirmar_importacao(self.con, analisar_arquivo(REFERENCIA), "2026-11-09")
        bom = banco.fazer_backup(self.tmp / "bk", self.db)
        self.con.close()
        with open(self.db, "r+b") as f:       # danifica o banco em uso
            f.seek(4096)
            f.write(os.urandom(32768))
        banco.restaurar_backup(bom, self.db)
        self.con = banco.conectar(self.db)
        self.assertEqual(banco.verificar_integridade(self.con), "ok")
        self.assertEqual(len(carregar_dataframe(self.con)), 203)
        guardados = list((self.tmp / "backups" / "antes_de_restaurar").glob("*.db"))
        self.assertEqual(len(guardados), 1)   # a cópia do arquivo danificado ficou guardada
