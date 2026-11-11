"""Dashboard público del Monitor financiero de México.

Lee los marts de dbt. Por defecto usa la foto versionada en dashboard/datos/
(así corre en Streamlit Community Cloud sin la base original). Con la variable
MONITOR_DB apuntando a monitor.duckdb lee los datos en vivo (NUC).

    streamlit run dashboard/app.py
"""
import json
import os
from datetime import timedelta
from pathlib import Path

import duckdb
import pandas as pd
import streamlit as st

DATOS = Path(__file__).resolve().parent / "datos"
REPO = "https://github.com/WillyyyFernandez/monitor-financiero"
MARTS = ["mart_indicadores_diarios", "mart_cripto_diario", "mart_cripto_vs_fix"]
RANGOS = {"3 meses": 92, "1 año": 366, "3 años": 3 * 366, "Todo": None}

st.set_page_config(page_title="Monitor financiero de México", page_icon=":material/monitoring:", layout="wide")


@st.cache_data(ttl=600)
def cargar() -> tuple[dict[str, pd.DataFrame], str]:
    """Devuelve los marts como DataFrames y una descripción del origen de los datos."""
    db = os.environ.get("MONITOR_DB")
    if db:
        con = duckdb.connect(db, read_only=True)
        tablas = {m: con.execute(f"select * from main.{m} order by fecha").df() for m in MARTS}
        con.close()
        return tablas, "datos en vivo"
    con = duckdb.connect()
    tablas = {m: con.execute(f"select * from read_parquet(?) order by fecha", [str(DATOS / f"{m}.parquet")]).df()
              for m in MARTS}
    con.close()
    corte = json.loads((DATOS / "corte.json").read_text())["exportado_utc"]
    return tablas, f"foto de los datos del {corte} UTC"


def recortar(df: pd.DataFrame, dias: int | None) -> pd.DataFrame:
    if dias is None:
        return df
    return df[df["fecha"] >= df["fecha"].max() - timedelta(days=dias)]


tablas, origen = cargar()
ind = tablas["mart_indicadores_diarios"]
ind["fecha"] = pd.to_datetime(ind["fecha"])
cripto = tablas["mart_cripto_diario"]
cripto["fecha"] = pd.to_datetime(cripto["fecha"])
prima = tablas["mart_cripto_vs_fix"]
prima["fecha"] = pd.to_datetime(prima["fecha"])
ultimo = ind.iloc[-1]

st.title("Monitor financiero de México", anchor=False)
st.caption(
    f"Tipo de cambio, tasas e inflación de Banxico y cripto de Binance, modelados con dbt sobre DuckDB "
    f"y orquestados con Dagster. Último dato: {ultimo['fecha']:%d/%m/%Y} · {origen} · "
    f"[código y documentación]({REPO})"
)

# ---- Indicadores clave ----
fx30 = ind["usd_mxn"].tail(30).tolist()
c1, c2, c3, c4 = st.columns(4)
c1.metric("USD/MXN (FIX)", f"{ultimo['usd_mxn']:.4f}", f"{ultimo['var_21_habiles_pct']:+.2f}% en 21 días hábiles",
          delta_color="inverse", chart_data=fx30, chart_type="area", border=True,
          help="Que baje el dólar significa que el peso se fortalece (verde).")
c2.metric("TIIE 28 días", f"{ultimo['tiie_28_pct']:.2f}%", border=True,
          chart_data=ind["tiie_28_pct"].tail(30).tolist(), chart_type="line")
c3.metric("Inflación anual", f"{ultimo['inflacion_anual_pct']:.2f}%", border=True,
          help="Variación anual del INPC; se considera conocida desde el mes siguiente.")
c4.metric("Tasa real (TIIE)", f"{ultimo['tasa_real_tiie_pct']:.2f}%", border=True,
          help="TIIE deflactada con la inflación anual vigente (fórmula de Fisher).")

rango = st.segmented_control("Periodo", list(RANGOS), default="1 año", label_visibility="collapsed")
dias = RANGOS[rango or "1 año"]

# ---- México ----
izq, der = st.columns(2)
with izq.container(border=True):
    st.subheader("Tipo de cambio FIX", anchor=False)
    st.line_chart(recortar(ind, dias), x="fecha", y="usd_mxn", x_label="", y_label="Pesos por dólar", height=300)
with der.container(border=True):
    st.subheader("Tasas e inflación", anchor=False)
    tasas = recortar(ind, dias).rename(columns={
        "tiie_28_pct": "TIIE 28 días", "inflacion_anual_pct": "Inflación anual", "tasa_real_tiie_pct": "Tasa real"})
    st.line_chart(tasas, x="fecha", y=["TIIE 28 días", "Inflación anual", "Tasa real"],
                  x_label="", y_label="%", height=300)

# ---- Cripto ----
izq, der = st.columns(2)
with izq.container(border=True):
    st.subheader("Bitcoin en pesos", anchor=False)
    btc = recortar(cripto[cripto["par"] == "BTCMXN"], dias)
    if btc.empty:
        st.caption("Binance lista BTCMXN desde mayo de 2024; no hay datos en este periodo.")
    else:
        st.line_chart(btc, x="fecha", y="cierre", x_label="", y_label="MXN", height=300)
with der.container(border=True):
    st.subheader("Prima de USDT frente al dólar oficial", anchor=False)
    usdt = recortar(prima[prima["activo"] == "USDT"], dias).copy()
    usdt["Promedio móvil 30 días"] = usdt["prima_vs_fix_pct"].rolling(30, min_periods=10).mean()
    usdt = usdt.rename(columns={"prima_vs_fix_pct": "Prima diaria"})
    st.line_chart(usdt, x="fecha", y=["Prima diaria", "Promedio móvil 30 días"], x_label="", y_label="%", height=300)
    st.caption("Cuánto más (o menos) cuesta un USDT en pesos en Binance que un dólar al tipo de cambio FIX. "
               "En fines de semana y feriados se usa el último FIX publicado.")

with st.expander("Cómo se construyen estos datos", icon=":material/account_tree:"):
    st.markdown(
        "- **Ingesta diaria (13:00 CDMX):** API del SIE de Banxico y velas públicas de Binance, guardadas como "
        "Parquet inmutable (capa bronze).\n"
        "- **dbt sobre DuckDB:** staging que se queda con la versión más reciente de cada dato, calendario bancario "
        "inferido de los datos, y marts con 43 tests de calidad y frescura.\n"
        "- **Dagster:** orquesta la carga y una revisión independiente de frescura a las 20:00.\n"
        "- **Agente:** un modelo local (Qwen2.5-14B) responde preguntas eligiendo funciones de solo lectura sobre "
        "estos mismos marts. Ese chat corre en el servidor propio, no en esta página.\n\n"
        f"Detalles y código en [GitHub]({REPO})."
    )
