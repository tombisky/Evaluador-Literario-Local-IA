from .base import llamar_modelo, extraer_json

PROMPT = """Fragmento:
\"\"\"{texto}\"\"\"

Lista SOLO los personajes humanos que aparecen o actúan en este fragmento.
No incluyas: objetos, lugares, conceptos, animales, instituciones.
Para cada uno indica si es nuevo (primera aparición) o conocido.

JSON: {{"entidades": [
  {{"nombre": "...", "es_nueva": true, "tipo": "protagonista|secundario|mencionado"}}
]}}"""

EXCLUIDOS = {
    # Lugares y conceptos
    "luna", "viento", "aire", "silencio", "ciudad", "mano",
    "orfanato", "albergue", "metro", "academia", "recuerdo",
    "voz", "sombra", "luz", "oscuridad", "tiempo", "destino",
    "habitacion", "habitación", "casa", "calle", "noche", "dia",
    "día", "mundo", "vida", "muerte", "miedo", "amor",
    # Partes del cuerpo y objetos que el modelo cuela como personajes
    "boca", "cuerpo", "rodilla", "criatura", "ojo", "ojos",
    "mano", "brazo", "pierna", "cara", "cabeza", "corazon",
    "corazón", "pecho", "espalda", "voz", "sombra", "reflejo",
    # Pronombres genéricos sin antecedente claro
    "ellos", "ellas", "ustedes", "vosotros", "nosotros", "alguien",
    "nadie", "persona", "gente"
}


def detectar(texto: str, escena: dict) -> list:
    respuesta = llamar_modelo(PROMPT.format(texto=texto[:1000]))
    datos = extraer_json(respuesta)
    if not isinstance(datos, dict):
        return []
    entidades = datos.get("entidades", [])
    resultado = []
    for e in entidades:
        if not isinstance(e, dict):
            continue
        nombre = str(e.get("nombre", "")).strip().lower()
        if not nombre or any(x in nombre for x in EXCLUIDOS):
            continue
        resultado.append(e)
    return resultado
