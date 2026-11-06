"""Capa bronze: cada descarga se guarda como un archivo Parquet nuevo e inmutable.

Estructura:
    data/bronze/<fuente>/fecha_carga=AAAA-MM-DD/<fuente>_<AAAAMMDDTHHMMSSZ>.parquet

Nunca se reescribe ni se borra un archivo: si una fuente corrige un dato, la
corrección llega en un archivo posterior y la capa staging de dbt se queda con la
versión más reciente (columna cargado_en). Así se puede reconstruir cualquier
estado pasado y auditar qué publicó cada fuente y cuándo.
"""
from datetime import datetime, timezone
from pathlib import Path

import duckdb

BRONZE_DIR = Path(__file__).parent.parent / "data" / "bronze"


def escribir(fuente: str, columnas: dict[str, str], filas: list[tuple]) -> Path | None:
    """Escribe las filas como un Parquet nuevo. columnas = {nombre: tipo DuckDB}.

    Agrega la columna cargado_en (UTC, igual para toda la descarga).
    Devuelve la ruta escrita, o None si no hay filas.
    """
    if not filas:
        return None
    ahora = datetime.now(timezone.utc).replace(microsecond=0)
    carpeta = BRONZE_DIR / fuente / f"fecha_carga={ahora.date().isoformat()}"
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{fuente}_{ahora.strftime('%Y%m%dT%H%M%SZ')}.parquet"
    if destino.exists():
        raise FileExistsError(f"{destino} ya existe; bronze no sobrescribe archivos")

    con = duckdb.connect()  # en memoria: no toca la base del proyecto
    defin = ", ".join(f"{c} {t}" for c, t in columnas.items())
    con.execute(f"create table t ({defin})")
    con.executemany(f"insert into t values ({', '.join('?' * len(columnas))})", filas)
    tmp = destino.with_suffix(".parquet.tmp")
    # Se escribe a un temporal y se renombra: un lector nunca ve un archivo a medias.
    con.execute(
        f"copy (select *, ?::timestamp as cargado_en from t) to '{tmp}' (format parquet)",
        [ahora.replace(tzinfo=None)],
    )
    con.close()
    tmp.rename(destino)
    return destino


def glob(fuente: str) -> str:
    return str(BRONZE_DIR / fuente / "*" / "*.parquet")


def hay_archivos(fuente: str) -> bool:
    return any((BRONZE_DIR / fuente).glob("*/*.parquet"))
