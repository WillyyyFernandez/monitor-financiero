"""Genera los datos de muestra que usa la CI (GitHub Actions).

Toma un recorte fijo de la capa bronze real (datos públicos de Banxico y Binance)
y lo guarda en ci/fixtures/bronze/, con la misma estructura que data/bronze/.
Así la CI corre `dbt build` sin red, sin tokens y siempre sobre los mismos datos.

Uso (desde la raíz del repo, con data/bronze/ ya poblado):
    python scripts/generar_fixtures_ci.py

Solo hace falta volver a correrlo si cambia el esquema de bronze.
"""
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "data" / "bronze"
DESTINO = RAIZ / "ci" / "fixtures" / "bronze"

# 15 meses: la inflación anual necesita 12 meses previos de INPC.
DESDE, HASTA = "2024-01-01", "2025-03-31"
# Hora de carga fija y anterior a la fecha de referencia de la CI (2025-04-02).
CARGADO_EN = "2025-04-01 19:00:00"

CONSULTAS = {
    "banxico_series": f"""
        select * exclude (cargado_en, fecha_carga), timestamp '{CARGADO_EN}' as cargado_en
        from read_parquet('{ORIGEN}/banxico_series/*/*.parquet', hive_partitioning = true)
        where strptime(fecha, '%d/%m/%Y')::date between '{DESDE}' and '{HASTA}'
        qualify row_number() over (partition by id_serie, fecha order by cargado_en desc) = 1
        order by id_serie, fecha
    """,
    "binance_klines": f"""
        select * exclude (cargado_en, fecha_carga), timestamp '{CARGADO_EN}' as cargado_en
        from read_parquet('{ORIGEN}/binance_klines/*/*.parquet', hive_partitioning = true)
        where to_timestamp(open_time_ms / 1000)::date between '{DESDE}' and '{HASTA}'
        qualify row_number() over (partition by par, open_time_ms order by cargado_en desc) = 1
        order by par, open_time_ms
    """,
}


def main() -> None:
    con = duckdb.connect()
    for fuente, sql in CONSULTAS.items():
        carpeta = DESTINO / fuente / "fecha_carga=2025-04-01"
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / f"{fuente}_fixture.parquet"
        con.execute(f"copy ({sql}) to '{destino}' (format parquet)")
        n = con.execute(f"select count(*) from read_parquet('{destino}')").fetchone()[0]
        print(f"{destino.relative_to(RAIZ)}: {n} filas, {destino.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
