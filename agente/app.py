"""Chat web mínimo para preguntarle al agente en lenguaje natural.

Corre en la misma máquina que el modelo (NUC) y solo escucha en localhost.
Cada pregunta es independiente: el agente no recuerda las anteriores.
El tema visual vive en .streamlit/config.toml (sin CSS propio).

    streamlit run agente/app.py
"""
import json
import sys
import time
from pathlib import Path

import requests
import streamlit as st

# `streamlit run agente/app.py` pone en sys.path la carpeta agente/, no la raíz
# del repo; sin esto, `import agente` falla.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agente import chat, funciones  # noqa: E402

AVATAR_USUARIO = ":material/person:"
AVATAR_AGENTE = ":material/query_stats:"

# Etiqueta del chip -> pregunta que se envía.
SUGERENCIAS = {
    ":blue[:material/currency_exchange:] Tipo de cambio y tasa real": "¿Cuál es el tipo de cambio más reciente y la tasa real?",
    ":blue[:material/trending_up:] El dólar en octubre": "¿Cuánto subió o bajó el dólar en octubre de 2026?",
    ":violet[:material/currency_bitcoin:] Bitcoin en pesos": "¿Cómo le fue a bitcoin en pesos en octubre de 2026?",
    ":green[:material/compare_arrows:] USDT vs dólar oficial": "¿El USDT en Binance está más caro que el dólar oficial? Usa todo 2025.",
}

NOMBRES_FUNCION = {
    "cobertura": "Revisó qué fechas hay disponibles",
    "ultimo_dato": "Consultó el último dato",
    "indicadores_periodo": "Resumió los indicadores del periodo",
    "tasa_real_mes": "Calculó la tasa real del mes",
    "cripto_periodo": "Consultó el precio cripto del periodo",
    "prima_cripto": "Comparó el precio cripto contra el FIX",
}

st.set_page_config(page_title="Monitor financiero de México", page_icon=":material/monitoring:")


@st.cache_data(ttl=300)
def _contexto() -> tuple[dict, list, list]:
    ultimo = funciones.ultimo_dato()["ultimo"]
    cobertura = funciones.cobertura()["cobertura"]
    serie = [f["usd_mxn"] for f in funciones._consulta(
        "select usd_mxn from (select fecha, usd_mxn from main.mart_indicadores_diarios "
        "order by fecha desc limit 30) order by fecha", [])]
    return ultimo, cobertura, serie


with st.sidebar:
    st.subheader("Último dato", anchor=False)
    try:
        ultimo, cobertura, serie = _contexto()
    except Exception as e:  # base bloqueada o ausente: el chat puede seguir
        st.warning(f"No pude leer la base: {e}", icon=":material/warning:")
    else:
        # Que baje el dólar es que el peso se fortalece: verde (delta_color="inverse").
        st.metric("USD/MXN (FIX)", f"{ultimo['usd_mxn']:.4f}", f"{ultimo['var_diaria_pct']:+.2f}% vs día anterior",
                  delta_color="inverse", chart_data=serie, chart_type="area", border=True)
        st.metric("TIIE 28 días", f"{ultimo['tiie_28_pct']:.2f}%", border=True)
        st.metric("Tasa real", f"{ultimo['tasa_real_tiie_pct']:.2f}%", border=True)
        st.caption(f"Fecha del dato: {ultimo['fecha']} · últimos 30 días hábiles en la gráfica")
        st.subheader("Datos disponibles", anchor=False)
        for c in cobertura:
            st.caption(f"{c['mart']}: {c['desde']} a {c['hasta']}")

st.title("Monitor financiero de México", anchor=False)
st.caption(
    "Pregunta en español sobre el tipo de cambio, la TIIE, la inflación, la tasa real y cripto "
    "(BTC, ETH, USDT). Un modelo local (Qwen2.5-14B) elige qué consulta hacer; las cifras salen "
    "de las tablas de dbt, no del modelo. En CPU cada respuesta tarda de 15 a 60 segundos."
)

if "historial" not in st.session_state:
    st.session_state["historial"] = []


def _mostrar_paso(paso: dict) -> None:
    with st.status(NOMBRES_FUNCION.get(paso["funcion"], paso["funcion"]), type="step", state="complete"):
        st.markdown(f"`{paso['funcion']}({paso['argumentos']})`")
        st.code(json.dumps(paso["resultado"], ensure_ascii=False, indent=2), language="json")


def _etiqueta(entrada: dict) -> str:
    n = len(entrada["traza"])
    consultas = "sin consultar datos" if n == 0 else f"{n} consulta{'s' if n > 1 else ''}"
    return f"Cómo lo calculó · {consultas} · {entrada['segundos']:.1f} s"


def _mostrar(entrada: dict) -> None:
    with st.chat_message("user", avatar=AVATAR_USUARIO):
        st.markdown(entrada["pregunta"])
    with st.chat_message("assistant", avatar=AVATAR_AGENTE):
        if entrada.get("error"):
            st.error(entrada["error"], icon=":material/error:")
            return
        with st.status(_etiqueta(entrada), type="compact", state="complete", expanded=False):
            for paso in entrada["traza"]:
                _mostrar_paso(paso)
        st.markdown(entrada["respuesta"])


for entrada in st.session_state["historial"]:
    _mostrar(entrada)

pregunta = st.chat_input("Escribe tu pregunta", submit_mode="disable")

# Sugerencias solo antes del primer mensaje; se ocultan en cuanto hay pregunta.
if not st.session_state["historial"]:
    hueco = st.empty()
    elegida = hueco.pills("Prueba con:", list(SUGERENCIAS), label_visibility="collapsed", key="sugerencia")
    if elegida and not pregunta:
        pregunta = SUGERENCIAS[elegida]
    if pregunta:
        hueco.empty()

if pregunta:
    entrada = {"pregunta": pregunta}
    traza: list = []
    inicio = time.time()
    with st.chat_message("user", avatar=AVATAR_USUARIO):
        st.markdown(pregunta)
    with st.chat_message("assistant", avatar=AVATAR_AGENTE):
        with st.status(":shimmer[Consultando el modelo y los datos]", type="compact") as estado:
            try:
                entrada["respuesta"] = chat.preguntar(pregunta, traza=traza, al_paso=_mostrar_paso)
            except requests.RequestException as e:
                entrada["error"] = f"No pude hablar con el modelo ({type(e).__name__}). ¿Está corriendo llama-server?"
            except (KeyError, SystemExit, OSError) as e:
                # OSError: no existe o no se puede leer el archivo de la llave
                entrada["error"] = f"Falta configuración del modelo: {e}"
            entrada["traza"], entrada["segundos"] = traza, time.time() - inicio
            estado.update(label=_etiqueta(entrada), state="error" if "error" in entrada else "complete",
                          expanded=False)
        if "error" in entrada:
            st.error(entrada["error"], icon=":material/error:")
        else:
            st.markdown(entrada["respuesta"])
    st.session_state["historial"].append(entrada)
