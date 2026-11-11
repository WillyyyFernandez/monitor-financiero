"""Exporta los marts a Parquet para el dashboard público (Streamlit Community Cloud).

El dashboard público no puede leer la base de la NUC, así que lee una foto de los
marts versionada en dashboard/datos/. Este script la regenera desde
data/monitor.duckdb (que se construye con la ingesta + `dbt build`).

Uso, desde la raíz del repo:
    python scripts/exportar_dashboard.py
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "data" / "monitor.duckdb"
DESTINO = RAIZ / "dashboard" / "datos"
MARTS = ["mart_indicadores_diarios", "mart_cripto_diario", "mart_cripto_vs_fix"]


def main() -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(ORIGEN), read_only=True)
    resumen = {}
    for mart in MARTS:
        destino = DESTINO / f"{mart}.parquet"
        con.execute(f"copy (select * from main.{mart} order by all) to '{destino}' (format parquet, compression zstd)")
        filas, hasta = con.execute(f"select count(*), max(fecha) from main.{mart}").fetchone()
        resumen[mart] = {"filas": filas, "hasta": hasta.isoformat()}
        print(f"{destino.relative_to(RAIZ)}: {filas} filas hasta {hasta}, {destino.stat().st_size // 1024} KB")
    con.close()
    (DESTINO / "corte.json").write_text(json.dumps(
        {"exportado_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"), "marts": resumen},
        indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
