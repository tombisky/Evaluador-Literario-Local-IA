import json
import os
import re
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

# Configuración del backend local. LM Studio expone una API compatible con
# OpenAI; el modelo concreto y el endpoint se configuran desde main.py (que
# setea las variables de entorno antes de importar este módulo).
#
# Variables reconocidas:
#   LM_STUDIO_BASE_URL  endpoint OpenAI-compatible
#   LM_STUDIO_MODEL     identificador del modelo cargado en LM Studio
#   LM_STUDIO_API_KEY   LM Studio la ignora, pero el SDK la exige (cualquier string)
BASE_URL = os.environ.get("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")
MODELO = os.environ.get("LM_STUDIO_MODEL", "")
API_KEY = os.environ.get("LM_STUDIO_API_KEY", "lm-studio")
UMBRAL = 0.35

_cliente = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def llamar_modelo(prompt: str) -> str:
    """Una llamada al modelo local vía LM Studio con temperatura 0.1."""
    try:
        r = _cliente.chat.completions.create(
            model=MODELO,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        )
        contenido = r.choices[0].message.content or ""
        return contenido.strip()
    except Exception as e:
        logger.error("Error LM Studio (%s): %s", MODELO, e)
        return ""


def extraer_json(texto: str) -> dict | list:
    """Limpia markdown y parsea JSON. Fallback por búsqueda de llaves."""
    if not texto:
        return {}
    limpio = re.sub(r"```(?:json)?\s*", "", texto)
    limpio = re.sub(r"```", "", limpio).strip()
    try:
        return json.loads(limpio)
    except Exception:
        pass
    m = re.search(r"\{.*\}", limpio, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    m = re.search(r"\[.*\]", limpio, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    logger.warning("No se pudo parsear JSON: %s", texto[:150])
    return {}
