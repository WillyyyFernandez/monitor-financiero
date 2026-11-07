"""Funciones analíticas que el LLM puede llamar (function calling).

El modelo NO escribe SQL: solo elige una de estas funciones y sus parámetros.
Cada función valida sus parámetros, usa consultas parametrizadas sobre los marts
y abre la base en modo de solo lectura, así el agente no puede modificar datos.
"""
import os
import time
from datetime import date
from pathlib import Path

import duckdb

DB_PATH = Path(os.environ.get("MONITOR_DB", Path(__file__).parent.parent / "data" / "monitor.duckdb"))
ACTIVOS = ("BTC", "ETH", "USDT")
MAX_DIAS = 3700  # ~10 años; evita consultas absurdas


class ErrorParametro(ValueError):
    """Parámetro inválido: se devuelve al modelo para que corrija su llamada."""


def _fecha(valor: str, nombre: str) -> date:
    try:
        return date.fromisoformat(str(valor))
    except ValueError:
        raise ErrorParametro(f"{nombre} debe tener formato AAAA-MM-DD, llegó {valor!r}")


def _rango(desde: str, hasta: str) -> tuple[date, date]:
    d, h = _fecha(desde, "desde"), _fecha(hasta, "hasta")
    if d > h:
        raise ErrorParametro("desde no puede ser posterior a hasta")
    if (h - d).days > MAX_DIAS:
        raise ErrorParametro(f"el rango máximo es de {MAX_DIAS} días")
    return d, h


def _activo(valor: str) -> str:
    a = str(valor).upper().strip()
    if a not in ACTIVOS:
        raise ErrorParametro(f"activo debe ser uno de {ACTIVOS}, llegó {valor!r}")
    return a


def _consulta(sql: str, params: list) -> list[dict]:
    """Solo lectura. Si Dagster está escribiendo (bloqueo de DuckDB), reintenta."""
    for intento in range(5):
        try:
            con = duckdb.connect(str(DB_PATH), read_only=True)
            try:
                cur = con.execute(sql, params)
                cols = [c[0] for c in cur.description]
                return [dict(zip(cols, fila)) for fila in cur.fetchall()]
            finally:
                con.close()
        except duckdb.IOException:
            if intento == 4:
                raise
            time.sleep(3)


def _redondear(filas: list[dict]) -> list[dict]:
    out = []
    for f in filas:
        out.append({k: (round(v, 4) if isinstance(v, float) else (v.isoformat() if isinstance(v, date) else v))
                    for k, v in f.items()})
    return out


def cobertura() -> dict:
    """Qué fechas cubre cada mart (útil para que el modelo no pida fechas sin datos)."""
    filas = _consulta(
        """select 'indicadores' as mart, min(fecha) as desde, max(fecha) as hasta from main.mart_indicadores_diarios
           union all select 'cripto', min(fecha), max(fecha) from main.mart_cripto_diario
           union all select 'cripto_vs_fix', min(fecha), max(fecha) from main.mart_cripto_vs_fix""",
        [],
    )
    return {"cobertura": _redondear(filas)}


def ultimo_dato() -> dict:
    """Última fila de indicadores de México (tipo de cambio, tasas, inflación, tasa real)."""
    filas = _consulta("select * from main.mart_indicadores_diarios order by fecha desc limit 1", [])
    return {"ultimo": _redondear(filas)[0] if filas else None}


def indicadores_periodo(desde: str, hasta: str) -> dict:
    """Resumen de indicadores de México entre dos fechas."""
    d, h = _rango(desde, hasta)
    filas = _consulta(
        """with p as (select * from main.mart_indicadores_diarios where fecha between ? and ?)
           select count(*) as dias_habiles,
                  min(fecha) as primera_fecha, max(fecha) as ultima_fecha,
                  arg_min(usd_mxn, fecha) as usd_mxn_inicio, arg_max(usd_mxn, fecha) as usd_mxn_fin,
                  min(usd_mxn) as usd_mxn_min, max(usd_mxn) as usd_mxn_max,
                  (arg_max(usd_mxn, fecha) / arg_min(usd_mxn, fecha) - 1) * 100 as variacion_usd_mxn_pct,
                  avg(tiie_28_pct) as tiie_promedio_pct,
                  avg(inflacion_anual_pct) as inflacion_anual_promedio_pct,
                  avg(tasa_real_tiie_pct) as tasa_real_promedio_pct
           from p""",
        [d, h],
    )
    r = _redondear(filas)[0]
    if not r["dias_habiles"]:
        return {"sin_datos": f"no hay días hábiles entre {d} y {h}", **cobertura()}
    return {"periodo": r}


def tasa_real_mes(mes: str) -> dict:
    """TIIE, inflación anual y tasa real promedio de un mes (AAAA-MM)."""
    inicio = _fecha(f"{mes}-01", "mes (formato AAAA-MM)")
    filas = _consulta(
        """select strftime(date_trunc('month', fecha), '%Y-%m') as mes,
                  avg(tiie_28_pct) as tiie_promedio_pct,
                  avg(inflacion_anual_pct) as inflacion_anual_pct,
                  avg(tasa_real_tiie_pct) as tasa_real_promedio_pct,
                  count(*) as dias_habiles
           from main.mart_indicadores_diarios
           where date_trunc('month', fecha) = ?
           group by 1""",
        [inicio],
    )
    if not filas:
        return {"sin_datos": f"no hay datos para {mes}", **cobertura()}
    return {"mes": _redondear(filas)[0]}


def cripto_periodo(activo: str, desde: str, hasta: str, moneda: str = "USDT") -> dict:
    """Precio, retorno y volatilidad de BTC o ETH entre dos fechas, en USDT o MXN."""
    a = _activo(activo)
    if a == "USDT":
        raise ErrorParametro("para USDT usa prima_cripto (USDT vs dólar oficial)")
    m = str(moneda).upper()
    if m not in ("USDT", "MXN"):
        raise ErrorParametro("moneda debe ser USDT o MXN")
    d, h = _rango(desde, hasta)
    filas = _consulta(
        """with p as (select * from main.mart_cripto_diario where par = ? and fecha between ? and ?)
           select count(*) as dias, min(fecha) as primera_fecha, max(fecha) as ultima_fecha,
                  arg_min(cierre, fecha) as cierre_inicio, arg_max(cierre, fecha) as cierre_fin,
                  min(cierre) as cierre_min, max(cierre) as cierre_max,
                  (arg_max(cierre, fecha) / arg_min(cierre, fecha) - 1) * 100 as retorno_periodo_pct,
                  stddev_samp(retorno_diario_pct) as volatilidad_diaria_pct
           from p""",
        [a + m, d, h],
    )
    r = _redondear(filas)[0]
    if not r["dias"]:
        return {"sin_datos": f"no hay velas de {a}{m} entre {d} y {h}", **cobertura()}
    return {"par": a + m, "periodo": r}


def prima_cripto(activo: str, desde: str, hasta: str) -> dict:
    """Prima del precio en pesos de Binance frente al precio con el FIX oficial."""
    a = _activo(activo)
    d, h = _rango(desde, hasta)
    filas = _consulta(
        """select count(prima_vs_fix_pct) as dias_con_dato,
                  avg(prima_vs_fix_pct) as prima_promedio_pct,
                  min(prima_vs_fix_pct) as prima_min_pct, max(prima_vs_fix_pct) as prima_max_pct,
                  avg(prima_vs_fix_pct) filter (where tipo_dia = 'habil') as prima_dias_habiles_pct,
                  avg(prima_vs_fix_pct) filter (where tipo_dia <> 'habil') as prima_dias_no_habiles_pct
           from main.mart_cripto_vs_fix
           where activo = ? and fecha between ? and ?""",
        [a, d, h],
    )
    r = _redondear(filas)[0]
    if not r["dias_con_dato"]:
        return {"sin_datos": f"no hay precio en pesos de {a} entre {d} y {h}", **cobertura()}
    return {"activo": a, "periodo": r}


FUNCIONES = {
    "cobertura": cobertura,
    "ultimo_dato": ultimo_dato,
    "indicadores_periodo": indicadores_periodo,
    "tasa_real_mes": tasa_real_mes,
    "cripto_periodo": cripto_periodo,
    "prima_cripto": prima_cripto,
}

_FECHA = {"type": "string", "description": "Fecha AAAA-MM-DD"}

HERRAMIENTAS = [
    {"type": "function", "function": {
        "name": "cobertura", "description": "Rango de fechas disponible en cada tabla de datos.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "ultimo_dato",
        "description": "Dato más reciente de México: tipo de cambio FIX USD/MXN, TIIE 28 días, CETES 28 días, inflación anual y tasa real.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "indicadores_periodo",
        "description": "Resumen entre dos fechas: tipo de cambio USD/MXN al inicio y al final, mínimo, máximo y variación; TIIE, inflación y tasa real promedio.",
        "parameters": {"type": "object", "properties": {"desde": _FECHA, "hasta": _FECHA},
                       "required": ["desde", "hasta"]}}},
    {"type": "function", "function": {
        "name": "tasa_real_mes",
        "description": "TIIE, inflación anual y tasa real promedio de un mes.",
        "parameters": {"type": "object", "properties": {
            "mes": {"type": "string", "description": "Mes AAAA-MM"}}, "required": ["mes"]}}},
    {"type": "function", "function": {
        "name": "cripto_periodo",
        "description": "Precio de cierre, retorno y volatilidad de BTC o ETH entre dos fechas.",
        "parameters": {"type": "object", "properties": {
            "activo": {"type": "string", "enum": ["BTC", "ETH"]},
            "desde": _FECHA, "hasta": _FECHA,
            "moneda": {"type": "string", "enum": ["USDT", "MXN"], "description": "Moneda del precio (por defecto USDT)"}},
            "required": ["activo", "desde", "hasta"]}}},
    {"type": "function", "function": {
        "name": "prima_cripto",
        "description": "Cuánto más (o menos) cuesta BTC, ETH o USDT en pesos en Binance comparado con el tipo de cambio oficial FIX.",
        "parameters": {"type": "object", "properties": {
            "activo": {"type": "string", "enum": list(ACTIVOS)},
            "desde": _FECHA, "hasta": _FECHA},
            "required": ["activo", "desde", "hasta"]}}},
]


def ejecutar(nombre: str, argumentos: dict) -> dict:
    """Ejecuta una llamada del modelo. Los errores de parámetros vuelven al modelo como texto."""
    if nombre not in FUNCIONES:
        return {"error": f"función desconocida {nombre!r}; disponibles: {list(FUNCIONES)}"}
    try:
        return FUNCIONES[nombre](**(argumentos or {}))
    except ErrorParametro as e:
        return {"error": str(e)}
    except TypeError as e:  # parámetros que la función no acepta
        return {"error": f"parámetros inválidos para {nombre}: {e}"}
