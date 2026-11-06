"""Ingesta incremental de velas diarias (klines) públicas de Binance hacia la capa bronze.

No requiere llave. Por cada par:
- Si no hay archivos en bronze, descarga todo desde DESDE.
- Si ya hay, vuelve a descargar solo desde las últimas SOLAPE velas guardadas.
  El solape cubre la vela del día en curso (que aún no cierra y cambia) y
  cualquier corrección reciente.
Cada corrida escribe un Parquet nuevo; nada se borra. Las velas repetidas entre
archivos se resuelven en staging (dbt) quedándose con la carga más reciente.

Uso:
    python -m ingesta.binance            # incremental
    python -m ingesta.binance --completo # vuelve a bajar todo el historial
"""
import sys
from datetime import datetime, timezone

import duckdb
from ingesta import bronze
from ingesta.http import get_json

API = "https://api.binance.com/api/v3/klines"
FUENTE = "binance_klines"
COLUMNAS = {
    "par": "varchar", "open_time_ms": "bigint", "open": "varchar", "high": "varchar",
    "low": "varchar", "close": "varchar", "volume": "varchar", "close_time_ms": "bigint",
    "quote_volume": "varchar", "trades": "bigint",
}
PARES = ["BTCUSDT", "ETHUSDT", "BTCMXN", "ETHMXN", "USDTMXN"]
DESDE = "2020-01-01"
SOLAPE = 3  # velas diarias que se vuelven a descargar en cada corrida incremental
DIA_MS = 86_400_000


def _get(params: dict) -> list:
    return get_json(API, params=params, timeout=30)


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


def _ultimas_velas() -> dict[str, int]:
    """Última open_time_ms guardada por par, leída de los Parquet de bronze."""
    if not bronze.hay_archivos(FUENTE):
        return {}
    con = duckdb.connect()
    filas = con.execute(
        "select par, max(open_time_ms) from read_parquet(?) group by par", [bronze.glob(FUENTE)]
    ).fetchall()
    con.close()
    return dict(filas)


def sincronizar(pares: list[str] = PARES, completo: bool = False) -> dict:
    """Descarga cada par y escribe un único Parquet con todo. Devuelve {par: velas}."""
    ultimas = {} if completo else _ultimas_velas()
    filas, resumen = [], {}
    for par in pares:
        ultimo = ultimas.get(par)
        inicio = _ms(DESDE) if ultimo is None else ultimo - (SOLAPE - 1) * DIA_MS
        nuevas = descargar_par(par, inicio)
        filas += nuevas
        resumen[par] = len(nuevas)
    bronze.escribir(FUENTE, COLUMNAS, filas)
    return resumen


if __name__ == "__main__":
    print(sincronizar(completo="--completo" in sys.argv))
