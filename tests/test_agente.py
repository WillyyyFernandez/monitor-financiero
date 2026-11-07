"""Pruebas del agente sin LLM: funciones contra la base real y bucle con un modelo falso.

Correr desde la raíz del repo, con data/monitor.duckdb construido:
    python -m pytest tests/ -q
"""
import json

import duckdb
import pytest

from agente import chat, funciones


def _valor(sql, params=()):
    con = duckdb.connect(str(funciones.DB_PATH), read_only=True)
    try:
        return con.execute(sql, list(params)).fetchone()[0]
    finally:
        con.close()


# ---- funciones: resultados coinciden con un cálculo independiente ----

def test_ultimo_dato_es_la_fecha_maxima():
    r = funciones.ultimo_dato()["ultimo"]
    assert r["fecha"] == _valor("select max(fecha) from main.mart_indicadores_diarios").isoformat()


def test_indicadores_periodo_variacion():
    r = funciones.indicadores_periodo("2025-01-01", "2025-12-31")["periodo"]
    ini = _valor("select usd_mxn from main.mart_indicadores_diarios where fecha >= '2025-01-01' order by fecha limit 1")
    fin = _valor("select usd_mxn from main.mart_indicadores_diarios where fecha <= '2025-12-31' order by fecha desc limit 1")
    assert r["variacion_usd_mxn_pct"] == pytest.approx((fin / ini - 1) * 100, abs=1e-3)


def test_tasa_real_mes():
    r = funciones.tasa_real_mes("2026-09")["mes"]
    esperado = _valor("select avg(tasa_real_tiie_pct) from main.mart_indicadores_diarios "
                      "where fecha between '2026-09-01' and '2026-09-30'")
    assert r["tasa_real_promedio_pct"] == pytest.approx(esperado, abs=1e-3)


def test_cripto_periodo_en_pesos():
    r = funciones.cripto_periodo("btc", "2025-06-01", "2025-06-30", moneda="mxn")
    assert r["par"] == "BTCMXN" and r["periodo"]["dias"] == 30


def test_prima_cripto_coincide():
    r = funciones.prima_cripto("USDT", "2025-01-01", "2025-12-31")["periodo"]
    esperado = _valor("select avg(prima_vs_fix_pct) from main.mart_cripto_vs_fix "
                      "where activo='USDT' and fecha between '2025-01-01' and '2025-12-31'")
    assert r["prima_promedio_pct"] == pytest.approx(esperado, abs=1e-3)


def test_periodo_sin_datos():
    r = funciones.indicadores_periodo("2010-01-01", "2010-12-31")
    assert "sin_datos" in r and "cobertura" in r


# ---- validación: lo que el modelo mande mal vuelve como error, no como excepción ----

@pytest.mark.parametrize("nombre,args", [
    ("indicadores_periodo", {"desde": "ayer", "hasta": "2025-01-01"}),
    ("indicadores_periodo", {"desde": "2025-02-01", "hasta": "2025-01-01"}),
    ("cripto_periodo", {"activo": "DOGE", "desde": "2025-01-01", "hasta": "2025-02-01"}),
    ("prima_cripto", {"activo": "BTC'; drop table x; --", "desde": "2025-01-01", "hasta": "2025-02-01"}),
    ("tasa_real_mes", {"mes": "septiembre"}),
    ("ultimo_dato", {"extra": 1}),
    ("borrar_todo", {}),
])
def test_parametros_invalidos_devuelven_error(nombre, args):
    assert "error" in funciones.ejecutar(nombre, args)


def test_la_base_se_abre_solo_lectura():
    con = duckdb.connect(str(funciones.DB_PATH), read_only=True)
    with pytest.raises(duckdb.Error):
        con.execute("create table intento (x int)")
    con.close()


def test_herramientas_coinciden_con_funciones():
    assert {h["function"]["name"] for h in funciones.HERRAMIENTAS} == set(funciones.FUNCIONES)


# ---- bucle de function calling con un modelo falso ----

def test_bucle_llama_funcion_y_responde():
    vistos = []

    def modelo_falso(mensajes):
        vistos.append(mensajes[-1]["role"])
        if mensajes[-1]["role"] == "user":
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
                "name": "prima_cripto", "arguments": json.dumps({"activo": "USDT", "desde": "2025-01-01", "hasta": "2025-12-31"})}}]}
        resultado = json.loads(mensajes[-1]["content"])
        return {"content": f"Prima promedio {resultado['periodo']['prima_promedio_pct']:.2f}%"}

    traza = []
    respuesta = chat.preguntar("prima de USDT en 2025", llamar=modelo_falso, traza=traza)
    assert respuesta.startswith("Prima promedio")
    assert vistos == ["user", "tool"]
    assert traza[0]["funcion"] == "prima_cripto"


def test_bucle_devuelve_error_al_modelo_si_argumentos_rotos():
    def modelo_falso(mensajes):
        if mensajes[-1]["role"] == "user":
            return {"content": "", "tool_calls": [{"id": "c1", "type": "function",
                                                   "function": {"name": "ultimo_dato", "arguments": "{no es json"}}]}
        return {"content": "error recibido: " + mensajes[-1]["content"]}

    assert "JSON" in chat.preguntar("x", llamar=modelo_falso)


def test_bucle_se_corta_si_el_modelo_no_termina():
    def modelo_terco(mensajes):
        return {"content": "", "tool_calls": [{"id": "c", "type": "function",
                                               "function": {"name": "cobertura", "arguments": "{}"}}]}

    assert "máximo" in chat.preguntar("x", llamar=modelo_terco)
