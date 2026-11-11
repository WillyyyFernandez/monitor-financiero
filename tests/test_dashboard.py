"""Prueba el dashboard público sin navegador, sobre la foto versionada en dashboard/datos/.

No necesita data/monitor.duckdb, así que también corre en la CI.
"""
from pathlib import Path

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "dashboard" / "app.py")
DATOS = RAIZ / "dashboard" / "datos"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("MONITOR_DB", raising=False)
    return AppTest.from_file(APP).run(timeout=60)


def test_carga_sin_errores(app):
    assert not app.exception
    assert [m.label for m in app.metric] == ["USD/MXN (FIX)", "TIIE 28 días", "Inflación anual", "Tasa real (TIIE)"]


def test_metrica_fix_coincide_con_la_foto(app):
    ultimo = duckdb.connect().execute(
        "select usd_mxn from read_parquet(?) order by fecha desc limit 1",
        [str(DATOS / "mart_indicadores_diarios.parquet")]).fetchone()[0]
    assert app.metric[0].value == f"{ultimo:.4f}"


@pytest.mark.parametrize("rango", ["3 meses", "1 año", "3 años", "Todo"])
def test_cada_periodo_carga(app, rango):
    app.button_group[0].set_value(rango).run(timeout=60)
    assert not app.exception


def test_foto_sin_columnas_inesperadas():
    # La foto pública solo debe tener columnas de los marts (sin rutas ni metadatos de carga).
    cols = {c for (c,) in duckdb.connect().execute(
        "select column_name from (describe select * from read_parquet(?))",
        [str(DATOS / "mart_indicadores_diarios.parquet")]).fetchall()}
    assert "cargado_en" not in cols and "fecha" in cols
