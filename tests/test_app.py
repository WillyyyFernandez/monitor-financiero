"""Prueba la interfaz de Streamlit sin navegador ni LLM (AppTest + modelo falso)."""
import json
from pathlib import Path

import pytest
import requests
from streamlit.testing.v1 import AppTest

from agente import chat

APP = str(Path(__file__).resolve().parent.parent / "agente" / "app.py")


def _modelo_falso(mensajes):
    if mensajes[-1]["role"] == "user":
        return {"content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {
            "name": "indicadores_periodo", "arguments": json.dumps({"desde": "2026-10-01", "hasta": "2026-10-31"})}}]}
    r = json.loads(mensajes[-1]["content"])["periodo"]
    return {"content": f"El dólar varió {r['variacion_usd_mxn_pct']:.2f}% en octubre de 2026."}


@pytest.fixture
def modelo_falso(monkeypatch):
    original = chat.preguntar
    monkeypatch.setattr(chat, "preguntar", lambda p, traza=None, al_paso=None:
                        original(p, llamar=_modelo_falso, traza=traza, al_paso=al_paso))


def test_carga_sin_errores_y_muestra_ultimo_dato():
    at = AppTest.from_file(APP).run(timeout=30)
    assert not at.exception
    assert any(m.label == "USD/MXN (FIX)" for m in at.metric)


def test_pregunta_muestra_respuesta_y_traza(modelo_falso):
    at = AppTest.from_file(APP).run(timeout=30)
    at.chat_input[0].set_value("¿Cuánto varió el dólar en octubre?").run(timeout=30)
    assert not at.exception
    textos = [m.value for m in at.markdown]
    assert any("2.33%" in t for t in textos)
    assert any("indicadores_periodo" in t for t in textos)


def test_sugerencia_lanza_la_pregunta_y_desaparece(modelo_falso):
    at = AppTest.from_file(APP).run(timeout=30)
    chips = at.button_group[0]
    chips.set_value(chips.options[1]).run(timeout=30)
    assert not at.exception
    assert at.session_state["historial"][0]["pregunta"].startswith("¿Cuánto subió o bajó el dólar")
    at.run(timeout=30)  # en la siguiente vuelta ya hay historial: no hay chips
    assert len(at.button_group) == 0


def test_al_paso_se_llama_por_cada_funcion():
    vistos = []
    chat.preguntar("x", llamar=lambda m: _modelo_falso(m), al_paso=vistos.append)
    assert [p["funcion"] for p in vistos] == ["indicadores_periodo"]


def test_modelo_caido_muestra_error_sin_romper(monkeypatch):
    def caido(p, traza=None, al_paso=None):
        raise requests.ConnectionError("sin servidor")
    monkeypatch.setattr(chat, "preguntar", caido)
    at = AppTest.from_file(APP).run(timeout=30)
    at.chat_input[0].set_value("hola").run(timeout=30)
    assert not at.exception
    assert "llama-server" in at.error[0].value



def test_sin_archivo_de_llave_muestra_error_sin_romper(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:9/v1")
    monkeypatch.setenv("LLM_API_KEY_FILE", str(tmp_path / "no-existe.key"))
    at = AppTest.from_file(APP).run(timeout=30)
    at.chat_input[0].set_value("hola").run(timeout=30)
    assert not at.exception
    assert "configuración" in at.error[0].value
