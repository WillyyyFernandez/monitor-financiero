"""Ingesta de series del SIE de Banxico hacia la capa bronze (Parquet inmutable).

Cada corrida descarga el historial completo de las series desde 2020 y lo guarda
como un archivo nuevo. Banxico puede revisar datos pasados; guardar la foto
completa de cada día permite ver esas revisiones. Son ~3,600 filas por corrida.
El token se lee de la variable de entorno BANXICO_TOKEN.
"""
import os
from datetime import date

from ingesta import bronze
from ingesta.http import get_json

API = "https://www.banxico.org.mx/SieAPIRest/service/v1/series"
FUENTE = "banxico_series"
COLUMNAS = {"id_serie": "varchar", "titulo": "varchar", "fecha": "varchar", "dato": "varchar"}

SERIES = {
    "SF43718": "tipo_cambio_fix_usd_mxn",
    "SF43783": "tiie_28_dias",
    "SF282": "cetes_28_dias",
    "SP1": "inpc_indice_general",
}


def descargar(token: str, desde: str = "2020-01-01") -> list[tuple]:
    ids = ",".join(SERIES)
    url = f"{API}/{ids}/datos/{desde}/{date.today().isoformat()}"
    datos = get_json(url, headers={"Bmx-Token": token})
    filas = []
    for serie in datos["bmx"]["series"]:
        for d in serie.get("datos", []):
            if d["dato"] in ("N/E", ""):  # Banxico marca "no existe"
                continue
            filas.append((serie["idSerie"], serie["titulo"].strip(), d["fecha"], d["dato"]))
    return filas


def sincronizar() -> dict:
    token = os.environ.get("BANXICO_TOKEN")
    if not token:
        raise SystemExit("Falta BANXICO_TOKEN en el entorno")
    filas = descargar(token)
    ruta = bronze.escribir(FUENTE, COLUMNAS, filas)
    return {"filas": len(filas), "archivo": str(ruta)}


if __name__ == "__main__":
    print(sincronizar())
