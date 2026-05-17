from .base import llamar_modelo, extraer_json

PROMPT = """Fragmento:
\"\"\"{texto}\"\"\"

Personajes: {nombres}
Emociones detectadas: {emociones}

¿Hay conflicto activo entre estos personajes?
Tipos: interpersonal, interno, persona_entorno, sin_conflicto
Si no hay conflicto claro: tipo sin_conflicto, intensidad 0.1

JSON: {{"tipo": "...", "entidades_involucradas": ["..."],
  "descripcion": "max 10 palabras", "intensidad": 0.0,
  "resolucion": "sin_resolver|resuelto|aplazado"}}"""


def detectar(texto: str, entidades: list, estados: list) -> dict:
    if not entidades:
        return {"tipo": "sin_conflicto", "intensidad": 0.1, "entidades_involucradas": []}
    nombres = [e["nombre"] for e in entidades if isinstance(e, dict)]
    emociones_resumen = [
        f"{e.get('entidad')}: {e.get('emocion_primaria')}"
        for e in estados if isinstance(e, dict)
    ]
    respuesta = llamar_modelo(PROMPT.format(
        texto=texto[:800],
        nombres=", ".join(nombres),
        emociones=", ".join(emociones_resumen)
    ))
    datos = extraer_json(respuesta)
    if not isinstance(datos, dict):
        return {"tipo": "sin_conflicto", "intensidad": 0.1, "entidades_involucradas": []}
    tipos_validos = ("interpersonal", "interno", "persona_entorno", "sin_conflicto")
    if datos.get("tipo") not in tipos_validos:
        datos["tipo"] = "sin_conflicto"
    return datos
