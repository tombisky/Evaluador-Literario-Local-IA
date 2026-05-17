"""
Evaluador editorial — usa el LLM para emitir una valoración profesional
de la novela en base a los índices procesados, con la rúbrica que
usaría una agencia literaria.

Cada criterio se evalúa con una llamada al LLM que recibe SOLO los datos
relevantes para ese criterio (no se vuelca toda la novela). El LLM
devuelve puntuación 1-10, argumento, referencias y, si la nota es <7,
una mejora concreta.

Esta es una evaluación EDITORIAL desde DATOS AGREGADOS. Tiene límites
honestos: criterios como Prosa, Voz u Originalidad se evalúan también
con muestras de fragmentos del texto original; criterios como Personajes,
Conflicto o Estructura emergen directamente de los índices.
"""
from __future__ import annotations

import json
import logging
import random
from collections import Counter
from pathlib import Path
from typing import Any

from .base import llamar_modelo, extraer_json

logger = logging.getLogger(__name__)

# (Letra, nombre, peso). Replica la rúbrica del "Evaluador editorial".
CRITERIOS = [
    ("A", "Voz narrativa", 0.20),
    ("B", "Estructura y ritmo", 0.18),
    ("C", "Personajes", 0.17),
    ("D", "Prosa", 0.15),
    ("E", "Mundo y verosimilitud interna", 0.13),
    ("F", "Tensión y enganche", 0.12),
    ("G", "Originalidad y posicionamiento", 0.05),
]

PROMPT_BASE = """Eres un lector editorial senior. Evalúas una novela de fantasía oscura psicológica en español de España, narrador en primera persona. Tu criterio es exigente, no produces elogios vacíos.

CRITERIO: {nombre_criterio}

QUÉ DEBES VALORAR:
{rubrica}

DATOS:
{datos}

INSTRUCCIONES (cumple TODAS):
1. Tu respuesta debe ser EXCLUSIVAMENTE un JSON válido. Empieza por `{{` y termina por `}}`. NO escribas ni una palabra antes o después del JSON.
2. Puntúa de 1 a 10 con un decimal. No redondees para suavizar.
3. Argumenta en 3-6 frases usando los datos concretos del bloque DATOS.
4. Si la puntuación es <7, da un cambio concreto que subiría la nota.
5. Si los datos son insuficientes, igualmente devuelve el JSON con puntuación estimada y `confianza` = "baja".

ESQUEMA (respétalo literal):
{{"puntuacion": 6.5, "argumento": "...", "referencias": ["...", "..."], "mejora": "...", "confianza": "alta|media|baja"}}"""

RUBRICAS = {
    "A": (
        "- Consistencia y singularidad de la voz del narrador.\n"
        "- Distancia narrativa controlada y deliberada.\n"
        "- Capacidad de la voz para sostener la lectura.\n"
        "- Diferenciación de voces si hay varios narradores."
    ),
    "B": (
        "- Coherencia del arco narrativo global.\n"
        "- Gestión del ritmo: aceleración, respiración, clímax.\n"
        "- Proporciones entre actos.\n"
        "- Eficacia de la apertura y el cierre."
    ),
    "C": (
        "- Profundidad y coherencia del protagonista.\n"
        "- Antagonista: presencia, amenaza, complejidad.\n"
        "- Personajes secundarios: funcionalidad vs. opacidad.\n"
        "- Credibilidad de las motivaciones."
    ),
    "D": (
        "- Calidad de la escritura frase a frase.\n"
        "- Control sintáctico y variedad rítmica.\n"
        "- Densidad: dónde sobra, dónde falta.\n"
        "- Errores ortotipográficos (eliminatorios si los hay)."
    ),
    "E": (
        "- Coherencia del universo narrativo.\n"
        "- Worldbuilding implícito vs. explícito.\n"
        "- Reglas del mundo: ¿el lector puede seguirlas sin glosario?"
    ),
    "F": (
        "- Capacidad de generar y sostener tensión.\n"
        "- Gestión de la información al lector.\n"
        "- Puntos de no-retorno: ¿existen y funcionan?"
    ),
    "G": (
        "- Qué aporta este texto que no exista ya.\n"
        "- A qué catálogo o colección encajaría."
    ),
}


# ----------------------------------------------------------------------
# Preparación de datos por criterio
# ----------------------------------------------------------------------
def _datos_voz(agregados: dict, muestras: list[str]) -> str:
    """A — modo narrativo + voz del narrador (curva emocional del narrador) + muestras."""
    dist = agregados["distribuciones"]
    narrador = next(
        (p for p in agregados["personajes_canonicos"]
         if p["tipo_predominante"] == "protagonista"),
        None,
    )
    lineas = []
    lineas.append("Distribución del modo narrativo (campo `modo`):")
    for k, v in dist.get("modo", {}).items():
        lineas.append(f"  - {k}: {v}")
    if narrador:
        ce = narrador["curva_emocional"]
        lineas.append(f"\nNarrador identificado: {narrador['nombre']}")
        emos = ", ".join(f"{e} ({n})" for e, n in ce["emociones_frecuentes"][:5])
        lineas.append(f"  Emociones recurrentes: {emos}")
        lineas.append(f"  Intensidad media: {ce['intensidad_media']}")
        lineas.append(f"  Estados disociativos: {ce['estados_disociativos']}")
    if muestras:
        lineas.append("\nMuestras de texto (inicio de fragmentos representativos):")
        for i, m in enumerate(muestras, 1):
            lineas.append(f"  [{i}] \"{m}\"")
    return "\n".join(lineas)


def _datos_estructura(agregados: dict, fragmentos_por_capitulo: dict[int, int]) -> str:
    """B — distribución de conflicto e intensidad a lo largo de los capítulos."""
    dist = agregados["distribuciones"]
    lineas = []
    lineas.append("Capítulos indexados: " + ", ".join(
        f"cap{c} ({n} fragmentos)" for c, n in sorted(fragmentos_por_capitulo.items())
    ))
    lineas.append("\nDistribución temporal global (analepsis/presente/...):")
    for k, v in dist.get("tiempo_secuencia", {}).items():
        lineas.append(f"  - {k}: {v}")
    lineas.append("\nDistribución de tipos de conflicto:")
    for k, v in dist.get("conflicto_tipo", {}).items():
        lineas.append(f"  - {k}: {v}")
    return "\n".join(lineas)


def _datos_personajes(agregados: dict) -> str:
    """C — fichas de los personajes principales."""
    lineas = []
    top = agregados["personajes_canonicos"][:8]
    for p in top:
        ce = p["curva_emocional"]
        cf = p["conflicto"]
        emos = ", ".join(f"{e} ({n})" for e, n in ce["emociones_frecuentes"][:4])
        tipos_c = ", ".join(f"{k} ({v})" for k, v in cf["tipos"].items())
        contras = ", ".join(f"{k} ({v})" for k, v in cf["contrapartes"].items())
        lineas.append(
            f"- {p['nombre']} ({p['tipo_predominante']}, "
            f"{p['apariciones']} apariciones en caps {p['capitulos']}): "
            f"emociones=[{emos}], intensidad_media={ce['intensidad_media']}, "
            f"disociativos={ce['estados_disociativos']}, cambios_abruptos={ce['cambios_abruptos']}; "
            f"conflicto=[{tipos_c}] con [{contras}]"
        )
    return "\n".join(lineas)


def _datos_prosa(muestras: list[str]) -> str:
    """D — solo muestras de texto, son lo único útil para juzgar prosa."""
    if not muestras:
        return "(Sin muestras de texto disponibles. No se puede evaluar prosa frase a frase.)"
    lineas = ["Muestras de fragmentos representativos:"]
    for i, m in enumerate(muestras, 1):
        lineas.append(f"\n  [{i}] \"{m}\"")
    return "\n".join(lineas)


def _datos_mundo(agregados: dict) -> str:
    """E — lugares + tipos de conflicto + escenas con elementos sobrenaturales."""
    dist = agregados["distribuciones"]
    lineas = []
    lineas.append("Lugares más recurrentes:")
    for k, v in list(dist.get("lugares", {}).items())[:10]:
        lineas.append(f"  - {k}: {v}")
    lineas.append("\nTipos de conflicto presentes:")
    for k, v in dist.get("conflicto_tipo", {}).items():
        lineas.append(f"  - {k}: {v}")
    return "\n".join(lineas)


def _datos_tension(agregados: dict) -> str:
    """F — curva de intensidad y resolución de conflictos."""
    dist = agregados["distribuciones"]
    lineas = []
    lineas.append("Paleta emocional global (top 10):")
    for k, v in list(dist.get("emociones", {}).items())[:10]:
        lineas.append(f"  - {k}: {v}")
    intensidades = []
    cambios = 0
    disociativos = 0
    for p in agregados["personajes_canonicos"][:5]:
        ce = p["curva_emocional"]
        if ce["intensidad_media"]:
            intensidades.append(ce["intensidad_media"])
        cambios += ce["cambios_abruptos"]
        disociativos += ce["estados_disociativos"]
    if intensidades:
        lineas.append(
            f"\nIntensidad emocional media en los 5 personajes principales: "
            f"{sum(intensidades)/len(intensidades):.2f}"
        )
    lineas.append(f"Cambios emocionales abruptos en personajes principales: {cambios}")
    lineas.append(f"Estados disociativos detectados: {disociativos}")
    return "\n".join(lineas)


def _datos_originalidad(agregados: dict) -> str:
    """G — paleta emocional + densidad de estados disociativos."""
    dist = agregados["distribuciones"]
    lineas = []
    lineas.append("Paleta emocional (top 15):")
    for k, v in list(dist.get("emociones", {}).items())[:15]:
        lineas.append(f"  - {k}: {v}")
    lineas.append(
        "\nNota: la presencia abundante de estados como disociacion, "
        "anestesia_emocional, hipervigilancia, ambivalencia o vacio "
        "suele indicar narrativa psicológica con trauma como motor."
    )
    return "\n".join(lineas)


PREPARADORES = {
    "A": _datos_voz,
    "B": _datos_estructura,
    "C": _datos_personajes,
    "D": _datos_prosa,
    "E": _datos_mundo,
    "F": _datos_tension,
    "G": _datos_originalidad,
}


# ----------------------------------------------------------------------
# Muestras de texto
# ----------------------------------------------------------------------
def _cargar_muestras(n: int = 3, max_chars: int = 400) -> list[str]:
    """Toma N fragmentos aleatorios del manuscrito en ficheros/."""
    carpeta = Path("ficheros")
    if not carpeta.exists():
        return []
    archivos = sorted(carpeta.glob("*.md"))
    if not archivos:
        return []
    muestras = []
    archivos_muestra = random.sample(archivos, min(n, len(archivos)))
    for f in archivos_muestra:
        try:
            txt = f.read_text(encoding="utf-8")
            txt = txt.replace("#", "").replace("*", "").strip()
            # Salta cabeceras vacías y queda con párrafo continuo
            txt = " ".join(txt.split())
            if len(txt) > max_chars:
                # Toma un trozo del centro, donde suele haber prosa "media"
                ini = max(0, len(txt) // 3)
                txt = txt[ini:ini + max_chars]
            muestras.append(txt.strip())
        except Exception:
            pass
    return muestras


# ----------------------------------------------------------------------
# Evaluación
# ----------------------------------------------------------------------
def _intentar_recuperar_puntuacion(texto: str) -> float | None:
    """Si el modelo devolvió texto fuera de JSON, intenta extraer un número
    cercano a la palabra 'puntuacion' o un valor del tipo 'N.N/10'.
    """
    import re as _re
    if not texto:
        return None
    m = _re.search(r"puntuaci[oó]n\D{0,5}(\d{1,2}(?:[.,]\d)?)", texto, _re.IGNORECASE)
    if not m:
        m = _re.search(r"(\d{1,2}(?:[.,]\d))\s*/\s*10", texto)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except Exception:
            return None
    return None


def _evaluar_criterio(
    letra: str,
    nombre: str,
    datos_str: str,
) -> dict:
    prompt = PROMPT_BASE.format(
        nombre_criterio=nombre,
        rubrica=RUBRICAS[letra],
        datos=datos_str,
    )
    respuesta = llamar_modelo(prompt)
    datos = extraer_json(respuesta)

    # Reintento si la respuesta no es un dict con puntuación parseable
    if not (isinstance(datos, dict) and "puntuacion" in datos):
        logger.warning("Criterio %s: primer intento sin JSON válido. Reintentando con prompt simplificado...", letra)
        prompt_simple = (
            f"Evalúa el criterio '{nombre}' de una novela usando estos datos:\n\n"
            f"{datos_str}\n\n"
            "Devuelve SOLO un JSON sin ningún texto antes ni después. El JSON debe tener "
            "exactamente estas claves: puntuacion (número 1-10 con un decimal), "
            "argumento (string), referencias (lista de strings), mejora (string), "
            "confianza ('alta'|'media'|'baja'). Empieza por { y termina por }."
        )
        respuesta = llamar_modelo(prompt_simple)
        datos = extraer_json(respuesta)

    if not (isinstance(datos, dict) and "puntuacion" in datos):
        # Último intento: extraer al menos una nota numérica del texto
        nota = _intentar_recuperar_puntuacion(respuesta)
        argumento = (
            "El modelo no estructuró su respuesta como JSON, pero se recuperó una "
            f"puntuación aproximada del texto libre."
            if nota is not None
            else "El modelo no produjo una valoración parseable para este criterio. "
            "Suele ocurrir cuando el prompt contiene muestras de texto con "
            "caracteres que confunden al parser. Considera reducir el tamaño de las muestras."
        )
        return {
            "puntuacion": nota,
            "argumento": argumento,
            "referencias": [],
            "mejora": "",
            "confianza": "baja",
        }

    try:
        datos["puntuacion"] = float(datos["puntuacion"])
    except Exception:
        datos["puntuacion"] = None
    # Defensa contra estructuras inesperadas
    datos.setdefault("argumento", "—")
    datos.setdefault("referencias", [])
    datos.setdefault("mejora", "")
    datos.setdefault("confianza", "media")
    if not isinstance(datos["referencias"], list):
        datos["referencias"] = [str(datos["referencias"])]
    return datos


def evaluar(agregados: dict, fragmentos_por_capitulo: dict[int, int]) -> dict:
    """Devuelve la evaluación completa con puntuación ponderada."""
    muestras = _cargar_muestras()
    resultados = {}
    suma_ponderada = 0.0
    peso_total = 0.0

    for letra, nombre, peso in CRITERIOS:
        preparador = PREPARADORES[letra]
        if letra in ("A",):
            datos_str = preparador(agregados, muestras)
        elif letra == "B":
            datos_str = preparador(agregados, fragmentos_por_capitulo)
        elif letra == "D":
            datos_str = preparador(muestras)
        else:
            datos_str = preparador(agregados)

        logger.info("Evaluando criterio %s (%s)...", letra, nombre)
        res = _evaluar_criterio(letra, nombre, datos_str)
        res["peso"] = peso
        resultados[letra] = {**res, "nombre": nombre}

        if isinstance(res["puntuacion"], (int, float)):
            suma_ponderada += res["puntuacion"] * peso
            peso_total += peso

    total = round(suma_ponderada / peso_total, 2) if peso_total else None

    # Veredicto global con LLM
    logger.info("Generando veredicto editorial...")
    resumen_criterios = "\n".join(
        f"- {r['nombre']} ({letra}): {r['puntuacion']}/10 — {r['argumento'][:120]}"
        for letra, r in resultados.items()
    )
    prompt_veredicto = (
        "Eres un lector editorial senior. Has evaluado una novela de fantasía oscura "
        "psicológica en español por criterios independientes. Sintetiza un veredicto "
        "editorial global de 6-9 líneas que responda: ¿en qué estado está el texto?, "
        "¿cuánto trabajo de revisión requiere para ser presentable a una agencia?, "
        "¿vale la pena ese trabajo dado el potencial? Sé concreto, sin frases hechas.\n\n"
        f"Puntuación total ponderada: {total}/10\n\n"
        f"Resumen de criterios:\n{resumen_criterios}\n\n"
        "Devuelve EXCLUSIVAMENTE este JSON:\n"
        '{\n  "veredicto": "6-9 líneas",\n  '
        '"problemas_mayores": ["..."],\n  '
        '"problemas_menores": ["..."],\n  '
        '"fortalezas": ["..."],\n  '
        '"proximos_pasos": ["acción concreta 1", "acción 2"]\n}'
    )
    respuesta = llamar_modelo(prompt_veredicto)
    veredicto = extraer_json(respuesta)
    if not isinstance(veredicto, dict):
        veredicto = {
            "veredicto": "(Sin veredicto del modelo.)",
            "problemas_mayores": [],
            "problemas_menores": [],
            "fortalezas": [],
            "proximos_pasos": [],
        }

    return {
        "criterios": resultados,
        "total_ponderado": total,
        "veredicto": veredicto,
        "muestras_usadas": len(muestras),
    }
