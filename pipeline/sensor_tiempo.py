from .base import llamar_modelo, extraer_json

PROMPT = """Fragmento:
\"\"\"{texto}\"\"\"

Tipo de secuencia temporal (elige uno):
presente_narrativo, analepsis, prolepsis, iterativo, elipsis

Ancla temporal: cuándo ocurre (max 5 palabras).
Duración implícita: horas | dias | indefinida

JSON: {{"tipo_secuencia": "...", "ancla": "...", "duracion": "..."}}"""


def detectar(texto: str) -> dict:
    respuesta = llamar_modelo(PROMPT.format(texto=texto[:800]))
    datos = extraer_json(respuesta)
    if not isinstance(datos, dict):
        return {"tipo_secuencia": "presente_narrativo", "ancla": "", "duracion": "indefinida"}
    tipos = ("presente_narrativo", "analepsis", "prolepsis", "iterativo", "elipsis")
    if datos.get("tipo_secuencia") not in tipos:
        datos["tipo_secuencia"] = "presente_narrativo"
    duraciones = ("horas", "dias", "indefinida")
    if datos.get("duracion") not in duraciones:
        datos["duracion"] = "indefinida"
    return datos
