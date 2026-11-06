"""Ingesta incremental de velas diarias (klines) públicas de Binance hacia DuckDB (esquema raw).

No requiere llave. Por cada par:
- Si no hay datos guardados, descarga todo desde DESDE.
- Si ya hay datos, vuelve a descargar solo las últimas SOLAPE velas en adelante.
  El solape cubre la vela del día en curso (que aún no cierra y cambia) y
  cualquier corrección reciente. Esas filas se borran y se reinsertan, así que
  repetir una corrida no duplica nada.

Uso:
    python -m ingesta.binance            # incremental
    python -m ingesta.binance --completo # rehace todo el historial
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import requests

API = "https://api.binance.com/api/v3/klines"
DB_PATH = Path(__file__).parent.parent / "data" / "monitor.duckdb"
PARES = ["BTCUSDT", "ETHUSDT", "BTCMXN", "ETHMXN", "USDTMXN"]
DESDE = "2020-01-01"
SOLAPE = 3  # velas diarias que se vuelven a descargar en cada corrida incremental
DIA_MS = 86_400_000


def _get(params: dict, intentos: int = 5) -> list:
    """GET con reintentos y espera exponencial ante fallos de red o 429/5xx."""
    for i in range(intentos):
        try:
            r = requests.get(API, params=params, timeout=30)
            if r.status_code in (418, 429) or r.status_code >= 500:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == intentos - 1:
                raise
            time.sleep(2**i)


def _ms(fecha_iso: str) -> int:
    return int(datetime.fromisoformat(fecha_iso).replace(tzinfo=timezone.utc).timestamp() * 1000)


def descargar_par(par: str, inicio_ms: int) -> list[tuple]:
    filas = []
    while True:
        velas = _get({"symbol": par, "interval": "1d", "startTime": inicio_ms, "limit": 1000})
        if not velas:
            break
        for v in velas:
            # open_time, open, high, low, close, volume, close_time, quote_volume, trades
            filas.append((par, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8]))
        if len(velas) < 1000:
            break
        inicio_ms = velas[-1][6] + 1
    return filas


def _asegurar_tabla(con) -> None:
    con.execute("create schema if not exists raw")
    con.execute(
        """create table if not exists raw.binance_klines (
            par varchar, open_time_ms bigint, open varchar, high varchar, low varchar,
            close varchar, volume varchar, close_time_ms bigint, quote_volume varchar,
            trades bigint, cargado_en timestamp default current_timestamp)"""
    )


def _inicio_incremental(con, par: str, completo: bool) -> int:
    ultimo = con.execute(
        "select max(open_time_ms) from raw.binance_klines where par = ?", [par]
    ).fetchone()[0]
    if completo or ultimo is None:
        return _ms(DESDE)
    return ultimo - (SOLAPE - 1) * DIA_MS


def sincronizar(pares: list[str] = PARES, completo: bool = False, db_path: Path = DB_PATH) -> dict:
    """Descarga y carga cada par. Devuelve {par: velas descargadas}."""
    con = duckdb.connect(str(db_path))
    _asegurar_tabla(con)
    resumen = {}
    for par in pares:
        inicio = _inicio_incremental(con, par, completo)
        filas = descargar_par(par, inicio)
        # Reemplazo atómico del tramo descargado: si algo falla, no queda a medias.
        con.execute("begin")
        con.execute(
            "delete from raw.binance_klines where par = ? and open_time_ms >= ?", [par, inicio]
        )
        if filas:
            con.executemany(
                """insert into raw.binance_klines
                   (par, open_time_ms, open, high, low, close, volume, close_time_ms,
                    quote_volume, trades)
                   values (?,?,?,?,?,?,?,?,?,?)""",
                filas,
            )
        con.execute("commit")
        resumen[par] = len(filas)
    con.close()
    return resumen


if __name__ == "__main__":
    print(sincronizar(completo="--completo" in sys.argv))
