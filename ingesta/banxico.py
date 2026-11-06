"""Ingesta de series del SIE de Banxico hacia DuckDB (esquema raw).

Idempotente: cada corrida reemplaza las filas de las series que descarga.
El token se lee de la variable de entorno BANXICO_TOKEN.
"""
import os
from datetime import date
from pathlib import Path

import duckdb
import requests

API = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"
DB_PATH = Path(__file__).parent.parent / "data" / "monitor.duckdb"

SERIES = {
    "SF43718": "tipo_cambio_fix_usd_mxn",
    "SF43783": "tiie_28_dias",
    "SF282": "cetes_28_dias",
    "SP1": "inpc_indice_general",
}


def descargar(token: str, desde: str = "2020-01-01") -> list[tuple]:
    ids = ",".join(SERIES)
    url = f"{API}/{ids}/datos/{desde}/{date.today().isoformat()}"
    resp = requests.get(url, headers={"Bmx-Token": token}, timeout=60)
    resp.raise_for_status()
    filas = []
    for serie in resp.json()["bmx"]["series"]:
        for d in serie.get("datos", []):
            if d["dato"] in ("N/E", ""):  # Banxico marca "no existe"
                continue
            filas.append((serie["idSerie"], serie["titulo"].strip(), d["fecha"], d["dato"]))
    return filas


def cargar(filas: list[tuple], db_path: Path = DB_PATH) -> int:
    con = duckdb.connect(str(db_path))
    con.execute("create schema if not exists raw")
    con.execute(
        """create table if not exists raw.banxico_series (
            id_serie varchar, titulo varchar, fecha varchar, dato varchar,
            cargado_en timestamp default current_timestamp)"""
    )
    con.execute("delete from raw.banxico_series where id_serie in (%s)" % ",".join("?" * len(SERIES)), list(SERIES))
    con.executemany("insert into raw.banxico_series (id_serie, titulo, fecha, dato) values (?,?,?,?)", filas)
    n = con.execute("select count(*) from raw.banxico_series").fetchone()[0]
    con.close()
    return n


def main() -> int:
    token = os.environ.get("BANXICO_TOKEN")
    if not token:
        raise SystemExit("Falta BANXICO_TOKEN en el entorno")
    return cargar(descargar(token))


if __name__ == "__main__":
    print("filas en raw.banxico_series:", main())
