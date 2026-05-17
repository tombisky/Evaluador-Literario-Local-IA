from .base import llamar_modelo, extraer_json

PROMPT = """Fragmento de novela:
\"\"\"{texto}\"\"\"

En una línea cada uno:
- tipo: presente_narrativo | analepsis | prolepsis | iterativo
- lugar: dónde ocurre (max 4 palabras)
- modo: dialogo | narracion | introspección | mixto

JSON: {{"tipo": "...", "lugar": "...", "modo": "..."}}"""


def detectar(texto: str) -> dict:
    respuesta = llamar_modelo(PROMPT.format(texto=texto[:1000]))
    datos = extraer_json(respuesta)
    if not isinstance(datos, dict):
        return {"tipo": "presente_narrativo", "lugar": "no determinado", "modo": "narracion"}
    # Normalizar
    tipos_validos = ("presente_narrativo", "analepsis", "prolepsis", "iterativo")
    if datos.get("tipo") not in tipos_validos:
        datos["tipo"] = "presente_narrativo"
    return datos
