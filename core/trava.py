"""Tranca de gravação para banco em pasta de rede.

Em pasta compartilhada (SMB), o travamento de arquivos do SQLite nem sempre é confiável.
Esta tranca adiciona uma camada simples: antes de uma gravação de várias etapas, o
computador cria o arquivo "<banco>.trava" de forma exclusiva (O_CREAT | O_EXCL, operação
atômica também em compartilhamentos Windows). Quem chega depois espera. Ao terminar, o
arquivo é apagado.

Se um computador travar ou desligar no meio, a tranca fica "abandonada": depois de
TRAVA_ABANDONADA_SEG sem atualização ela é removida e a gravação segue.
"""
from __future__ import annotations

import json
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path

ESPERA_MAX_SEG = 120          # quanto tempo esperar a vez antes de desistir
TRAVA_ABANDONADA_SEG = 600    # 10 min: uma gravação real nunca dura tanto
INTERVALO_SEG = 0.2


class TravaOcupada(RuntimeError):
    pass


def caminho_trava(caminho_banco: Path | str) -> Path:
    return Path(f"{caminho_banco}.trava")


def quem_trava(caminho_banco: Path | str) -> dict | None:
    try:
        return json.loads(caminho_trava(caminho_banco).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@contextmanager
def trava_gravacao(caminho_banco: Path | str, usuario: str | None = None,
                   espera_max: float = ESPERA_MAX_SEG, abandonada: float = TRAVA_ABANDONADA_SEG):
    arq = caminho_trava(caminho_banco)
    dono = json.dumps({"computador": socket.gethostname(), "pid": os.getpid(), "usuario": usuario,
                       "desde": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False)
    inicio = time.monotonic()
    while True:
        try:
            fd = os.open(arq, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                idade = time.time() - arq.stat().st_mtime
            except FileNotFoundError:
                continue  # acabou de ser liberada: tenta de novo já
            if idade > abandonada:
                try:
                    arq.unlink()
                except FileNotFoundError:
                    pass
                continue
            if time.monotonic() - inicio > espera_max:
                info = quem_trava(caminho_banco) or {}
                raise TravaOcupada(
                    f"Outra gravação está em andamento há muito tempo (computador "
                    f"{info.get('computador', '?')}, usuário {info.get('usuario') or '?'}). Tente de novo em instantes.")
            time.sleep(INTERVALO_SEG)
            continue
        try:
            os.write(fd, dono.encode("utf-8"))
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        try:
            arq.unlink()
        except FileNotFoundError:
            pass
