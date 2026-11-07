"""Agente de preguntas en lenguaje natural sobre los marts.

Usa un servidor compatible con la API de OpenAI (llama-server en la NUC) con
function calling. El modelo elige funciones de agente/funciones.py; nosotros
ejecutamos el SQL y le devolvemos el resultado para que redacte la respuesta.

Variables de entorno:
    LLM_BASE_URL  p. ej. http://127.0.0.1:8081/v1
    LLM_API_KEY_FILE  ruta a un archivo con la llave del llama-server (preferido:
                      la llave no queda en variables de entorno ni en .env)
    LLM_API_KEY       alternativa: la llave directamente (nunca en el código)
    LLM_MODEL     nombre del modelo que expone el servidor

Uso:
    python -m agente.chat "¿Cuánto subió el dólar en octubre de 2026?"
"""
import json
import os
import sys
import time
from datetime import date

import requests

from agente import funciones

MAX_PASOS = 5

INSTRUCCIONES = """Eres un analista financiero que responde en español sobre datos de México
(tipo de cambio FIX, TIIE, CETES, inflación, tasa real) y cripto (BTC, ETH, USDT) de Banxico y Binance.
Hoy es {hoy}.
Reglas:
- Responde SOLO con cifras que vengan de las funciones. Si no hay datos, dilo.
- Convierte fechas relativas ("el mes pasado", "este año") a fechas AAAA-MM-DD antes de llamar.
- Si no sabes qué fechas hay disponibles, llama primero a cobertura.
- Da números con 2 decimales y di de qué periodo son. Sé breve."""


def _llave() -> str:
    ruta = os.environ.get("LLM_API_KEY_FILE")
    if ruta:
        with open(ruta) as f:
            return f.read().strip()
    if os.environ.get("LLM_API_KEY"):
        return os.environ["LLM_API_KEY"]
    raise SystemExit("Falta LLM_API_KEY_FILE o LLM_API_KEY")


def _llamar_modelo(mensajes: list[dict]) -> dict:
    url = os.environ["LLM_BASE_URL"].rstrip("/") + "/chat/completions"
    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {_llave()}"},
        json={
            "model": os.environ.get("LLM_MODEL", "local"),
            "messages": mensajes,
            "tools": funciones.HERRAMIENTAS,
            "tool_choice": "auto",
            "temperature": 0,
        },
        timeout=600,  # en CPU una respuesta puede tardar minutos
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]


def preguntar(pregunta: str, llamar=_llamar_modelo, traza: list | None = None) -> str:
    """Bucle de function calling. `llamar` se puede sustituir en pruebas."""
    mensajes = [
        {"role": "system", "content": INSTRUCCIONES.format(hoy=date.today().isoformat())},
        {"role": "user", "content": pregunta},
    ]
    for _ in range(MAX_PASOS):
        msg = llamar(mensajes)
        llamadas = msg.get("tool_calls") or []
        if not llamadas:
            return msg.get("content") or ""
        mensajes.append({"role": "assistant", "content": msg.get("content") or "", "tool_calls": llamadas})
        for ll in llamadas:
            nombre = ll["function"]["name"]
            try:
                args = json.loads(ll["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                resultado = {"error": "los argumentos no son JSON válido"}
            else:
                resultado = funciones.ejecutar(nombre, args)
            if traza is not None:
                traza.append({"funcion": nombre, "argumentos": ll["function"].get("arguments"), "resultado": resultado})
            mensajes.append({"role": "tool", "tool_call_id": ll.get("id", nombre),
                             "content": json.dumps(resultado, ensure_ascii=False)})
    return "No pude completar la respuesta en el número máximo de pasos."


def main() -> None:
    pregunta = " ".join(sys.argv[1:]) or input("Pregunta: ")
    traza: list = []
    inicio = time.time()
    respuesta = preguntar(pregunta, traza=traza)
    for t in traza:
        print(f"[funcion] {t['funcion']}({t['argumentos']})", file=sys.stderr)
    print(respuesta)
    print(f"[{time.time() - inicio:.1f} s]", file=sys.stderr)


if __name__ == "__main__":
    main()
