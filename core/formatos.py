"""Conversões de valores monetários e datas.

Regras:
- Valores monetários são armazenados em CENTAVOS (inteiro) para evitar erros
  de arredondamento de ponto flutuante. O valor original da planilha é
  preservado separadamente, sem alteração.
- Datas são armazenadas em ISO (AAAA-MM-DD) e exibidas em DD/MM/AAAA.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


class ValorInvalido(ValueError):
    pass


def para_centavos(valor) -> int | None:
    """Converte um valor da planilha em centavos (int).

    Aceita int/float/Decimal ou texto nos formatos '1234.56', '1.234,56',
    'R$ 1.234,56'. Retorna None para célula vazia. Lança ValorInvalido se
    o conteúdo não for numérico.
    """
    if valor is None:
        return None
    if isinstance(valor, bool):
        raise ValorInvalido(f"valor booleano não é monetário: {valor!r}")
    if isinstance(valor, (int, Decimal)):
        d = Decimal(valor)
    elif isinstance(valor, float):
        # str() devolve a representação mais curta (96.95 -> '96.95'),
        # evitando que 96.95 vire 96.9499999...
        d = Decimal(str(valor))
    else:
        texto = str(valor).strip()
        if texto == "":
            return None
        texto = texto.replace("R$", "").replace(" ", "").replace(" ", "")
        if "," in texto:  # padrão brasileiro: ponto = milhar, vírgula = decimal
            texto = texto.replace(".", "").replace(",", ".")
        try:
            d = Decimal(texto)
        except InvalidOperation as exc:
            raise ValorInvalido(f"valor não numérico: {valor!r}") from exc
    return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def formatar_brl(centavos: int | None) -> str:
    """12345 -> 'R$ 123,45'."""
    if centavos is None:
        return "—"
    sinal = "-" if centavos < 0 else ""
    c = abs(int(centavos))
    inteiro, dec = divmod(c, 100)
    inteiro_fmt = f"{inteiro:,}".replace(",", ".")
    return f"{sinal}R$ {inteiro_fmt},{dec:02d}"


_RE_DATA_BR = re.compile(r"^(\d{2})/(\d{2})/(\d{4})(?:\s*(?:às)?\s*(\d{2}):(\d{2})(?::(\d{2}))?)?$")
# Formato corrompido encontrado na coluna "Data de Liquidação" da planilha de
# referência: '09T03:00:00.000Z/11/2026' (um ISO 2026-11-09T03:00:00.000Z cujo
# ano/mês foram substituídos). Dia = 09, mês = 11, ano = 2026.
_RE_DATA_CORROMPIDA = re.compile(r"^(\d{2})T[\d:.]+Z/(\d{2})/(\d{4})$")
_RE_ISO = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2}))?.*)?$")


class DataInvalida(ValueError):
    pass


def interpretar_data(valor) -> tuple[datetime | None, bool]:
    """Retorna (datetime, corrigido). `corrigido` indica que o texto estava
    em formato fora do padrão e foi interpretado (para sinalizar ao usuário).
    """
    if valor is None:
        return None, False
    if isinstance(valor, datetime):
        return valor, False
    if isinstance(valor, date):
        return datetime(valor.year, valor.month, valor.day), False
    texto = str(valor).strip()
    if texto == "":
        return None, False
    m = _RE_DATA_BR.match(texto)
    if m:
        d, mth, a, hh, mm, ss = m.groups()
        try:
            return datetime(int(a), int(mth), int(d), int(hh or 0), int(mm or 0), int(ss or 0)), False
        except ValueError as exc:
            raise DataInvalida(f"data inexistente: {texto!r}") from exc
    m = _RE_DATA_CORROMPIDA.match(texto)
    if m:
        d, mth, a = m.groups()
        try:
            return datetime(int(a), int(mth), int(d)), True
        except ValueError as exc:
            raise DataInvalida(f"data inexistente: {texto!r}") from exc
    m = _RE_ISO.match(texto)
    if m:
        a, mth, d, hh, mm, ss = m.groups()
        try:
            return datetime(int(a), int(mth), int(d), int(hh or 0), int(mm or 0), int(ss or 0)), False
        except ValueError as exc:
            raise DataInvalida(f"data inexistente: {texto!r}") from exc
    raise DataInvalida(f"formato de data não reconhecido: {texto!r}")


def formatar_data(iso: str | date | None) -> str:
    if not iso:
        return "—"
    if isinstance(iso, (date, datetime)):
        return iso.strftime("%d/%m/%Y")
    a, m, d = str(iso)[:10].split("-")
    return f"{d}/{m}/{a}"
