"""Chat web mínimo para preguntarle al agente en lenguaje natural.

Corre en la misma máquina que el modelo (NUC) y solo escucha en localhost.
Cada pregunta es independiente: el agente no recuerda las anteriores.

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

EJEMPLOS = [
    "¿Cuál es el tipo de cambio más reciente y la tasa real?",
    "¿Cuánto subió o bajó el dólar en octubre de 2026?",
    "¿Cómo le fue a bitcoin en pesos en octubre de 2026?",
    "¿El USDT en Binance está más caro que el dólar oficial? Usa todo 2025.",
]

st.set_page_config(page_title="Monitor financiero de México", page_icon="📈")
st.title("📈 Monitor financiero de México")
st.caption(
    "Pregunta en español sobre el tipo de cambio, la TIIE, la inflación, la tasa real "
    "y cripto (BTC, ETH, USDT). Un modelo local (Qwen2.5-14B) elige qué consulta hacer; "
    "las cifras salen de las tablas de dbt, no del modelo."
)


@st.cache_data(ttl=300)
def _contexto() -> tuple[dict, list]:
    return funciones.ultimo_dato()["ultimo"], funciones.cobertura()["cobertura"]


with st.sidebar:
    st.subheader("Último dato")
    try:
        ultimo, cobertura = _contexto()
    except Exception as e:  # base bloqueada o ausente: el chat puede seguir
        st.warning(f"No pude leer la base: {e}")
    else:
        st.metric("USD/MXN (FIX)", f"{ultimo['usd_mxn']:.4f}", f"{ultimo['var_diaria_pct']:+.2f}% vs día anterior",
                  delta_color="inverse")
        st.metric("TIIE 28 días", f"{ultimo['tiie_28_pct']:.2f}%")
        st.metric("Tasa real", f"{ultimo['tasa_real_tiie_pct']:.2f}%")
        st.caption(f"Fecha: {ultimo['fecha']}")
        st.subheader("Datos disponibles")
        for c in cobertura:
            st.caption(f"{c['mart']}: {c['desde']} a {c['hasta']}")
    st.subheader("Ejemplos")
    for ej in EJEMPLOS:
        if st.button(ej, use_container_width=True):
            st.session_state["pendiente"] = ej
    st.caption("En CPU cada respuesta tarda de 15 a 60 segundos.")

if "historial" not in st.session_state:
    st.session_state["historial"] = []


def _mostrar(entrada: dict) -> None:
    with st.chat_message("user"):
        st.markdown(entrada["pregunta"])
    with st.chat_message("assistant"):
        if entrada.get("error"):
            st.error(entrada["error"])
            return
        st.markdown(entrada["respuesta"])
        detalle = f"{len(entrada['traza'])} consulta(s) · {entrada['segundos']:.1f} s"
        with st.expander(f"Cómo lo calculó ({detalle})"):
            if not entrada["traza"]:
                st.caption("El modelo respondió sin consultar datos.")
            for t in entrada["traza"]:
                st.markdown(f"**`{t['funcion']}`** con `{t['argumentos']}`")
                st.code(json.dumps(t["resultado"], ensure_ascii=False, indent=2), language="json")


for entrada in st.session_state["historial"]:
    _mostrar(entrada)

pregunta = st.chat_input("Escribe tu pregunta") or st.session_state.pop("pendiente", None)
if pregunta:
    entrada = {"pregunta": pregunta}
    traza: list = []
    inicio = time.time()
    with st.spinner("Consultando el modelo y los datos..."):
        try:
            entrada["respuesta"] = chat.preguntar(pregunta, traza=traza)
        except requests.RequestException as e:
            entrada["error"] = f"No pude hablar con el modelo ({type(e).__name__}). ¿Está corriendo llama-server?"
        except (KeyError, SystemExit, OSError) as e:
            # OSError: no existe o no se puede leer el archivo de la llave
            entrada["error"] = f"Falta configuración del modelo: {e}"
    entrada["traza"], entrada["segundos"] = traza, time.time() - inicio
    st.session_state["historial"].append(entrada)
    _mostrar(entrada)
