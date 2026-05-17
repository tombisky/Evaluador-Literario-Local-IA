from .base import llamar_modelo, extraer_json, UMBRAL

TAXONOMIA = (
    "serenidad, alegria, euforia, aceptacion, confianza, admiracion, "
    "aprehension, miedo, terror, distraccion, sorpresa, asombro, "
    "melancolia, tristeza, pena, aburrimiento, asco, repulsion, "
    "molestia, ira, rabia, interes, anticipacion, vigilancia, "
    "amor, culpa, curiosidad, desesperacion, dominancia, envidia, "
    "esperanza, fatalismo, morbo, nostalgia, orgullo, remordimiento, "
    "resignacion, verguenza, disociacion, despersonalizacion, "
    "anestesia_emocional, hipervigilancia, paralisis, ambivalencia, vacio"
)

PROMPT = """Fragmento:
\"\"\"{texto}\"\"\"

Personajes presentes: {nombres}

Para cada personaje, ¿qué emoción muestra? Usa SOLO: {taxonomia}
Intensidad 0.3-1.0. Si no hay emoción clara, omite el personaje.
Detonante: max 6 palabras.

JSON: {{"estados": [
  {{"entidad": "...", "emocion_primaria": "...", "intensidad_primaria": 0.0,
    "emocion_secundaria": "...", "intensidad_secundaria": 0.0,
    "detonante": "...", "cambio_abrupto": false}}
]}}"""


def detectar(texto: str, entidades: list) -> list:
    if not entidades:
        return []
    nombres = [e["nombre"] for e in entidades if isinstance(e, dict)]
    if not nombres:
        return []
    respuesta = llamar_modelo(PROMPT.format(
        texto=texto[:1000],
        nombres=", ".join(nombres),
        taxonomia=TAXONOMIA
    ))
    datos = extraer_json(respuesta)
    if not isinstance(datos, dict):
        return []
    estados = datos.get("estados", [])
    # Filtrar por umbral
    return [
        e for e in estados
        if isinstance(e, dict)
        and float(e.get("intensidad_primaria", 0)) >= UMBRAL
    ]
