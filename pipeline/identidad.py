"""
Integrador_Identidad — unifica aliases que se refieren al mismo personaje.

El sensor_entidad clasifica fragmento a fragmento, así que un mismo
personaje aparece con muchos nombres distintos a lo largo del manuscrito:
"yo", "narrador", "narrador_protagonista", "alba", "el chico", "chico_1",
etc. Sin unificación, las fichas agregadas están fragmentadas.

Estrategia: mandar al LLM la lista de aliases con su huella (tipo
predominante, capítulos, emociones top, contrapartes en conflicto) y
pedirle que agrupe los que se refieren al mismo personaje real.

El mapa resultante se guarda en `indices/meta/aliases.json` y solo se
regenera con --reset (o si el archivo no existe).
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path

from .base import llamar_modelo, extraer_json

logger = logging.getLogger(__name__)

MAPA_PATH = Path("indices/meta/aliases.json")

PROMPT = """Tarea: agrupar aliases que se refieren al MISMO personaje real en una novela en primera persona en español.

Pistas:
- La novela tiene narrador en PRIMERA persona. Cualquier alias del tipo \"yo\", \
\"narrador\", \"narradora\", \"narrador_protagonista\", \"yo_me\" y derivados es \
LA MISMA persona, que probablemente sea uno de los nombres propios listados \
(busca el nombre propio con mayor número de apariciones del tipo \"protagonista\" \
y agrúpalo junto con todos los aliases del narrador).
- Aliases del tipo \"el chico\", \"chico_1\", \"chico_2\" suelen referirse al MISMO \
chico si comparten tipo y capítulos. Solo agrúpalos si los datos lo apoyan.
- Nombres propios distintos (Alba, Drik, Ruby, Bruno, Tomás, Cecilia, Félix...) \
son personajes distintos: NO los unifiques entre sí.

Candidatos detectados:
{candidatos}

Devuelve un JSON con grupos. Cada grupo tiene un \"canonico\" (el nombre \
canónico, idealmente un nombre propio si existe, si no el alias más frecuente) \
y una lista \"aliases\" con los nombres que se unifican bajo él. CADA alias de la \
lista debe aparecer en EXACTAMENTE un grupo. No inventes aliases.

JSON: {{"grupos": [
  {{"canonico": "...", "aliases": ["...", "..."]}}
]}}"""


def _huella_personaje(
    nombre_archivo: str,
    apariciones: list,
    emocional: list,
    conflicto: list,
) -> dict:
    """Resume un personaje en un dict compacto que se le pasa al LLM."""
    nombre_real = nombre_archivo
    if apariciones and isinstance(apariciones[0], dict):
        nombre_real = apariciones[0].get("personaje", nombre_archivo)

    tipos = Counter(e.get("tipo", "?") for e in apariciones if isinstance(e, dict))
    capitulos = sorted({e.get("capitulo") for e in apariciones if isinstance(e, dict) and e.get("capitulo")})
    emos = Counter()
    for e in emocional:
        if isinstance(e, dict):
            emos[e.get("emocion_primaria", "?")] += 1
    contrapartes = Counter()
    for c in conflicto:
        if isinstance(c, dict):
            for inv in c.get("entidades_involucradas", []) or []:
                if inv and inv != nombre_real:
                    contrapartes[inv] += 1

    return {
        "alias": nombre_archivo,
        "nombre_visible": nombre_real,
        "apariciones": len(apariciones),
        "tipo": tipos.most_common(1)[0][0] if tipos else "?",
        "capitulos": capitulos,
        "top_emociones": [e for e, _ in emos.most_common(3)],
        "contrapartes": [c for c, _ in contrapartes.most_common(3)],
    }


def _construir_candidatos(huellas: list[dict]) -> str:
    """Convierte las huellas en un bloque de texto para el prompt."""
    lineas = []
    for h in huellas:
        cap_str = ",".join(str(c) for c in h["capitulos"]) or "—"
        emos = ", ".join(h["top_emociones"]) or "—"
        contras = ", ".join(h["contrapartes"]) or "—"
        lineas.append(
            f"- alias='{h['alias']}' (visible='{h['nombre_visible']}'), "
            f"tipo={h['tipo']}, apariciones={h['apariciones']}, "
            f"caps=[{cap_str}], emociones=[{emos}], contrapartes=[{contras}]"
        )
    return "\n".join(lineas)


def _cargar_indice_dir(dir_: str) -> dict[str, list]:
    res = {}
    p = Path(f"indices/{dir_}")
    if not p.exists():
        return res
    for f in p.glob("*.json"):
        try:
            datos = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(datos, list):
                res[f.stem] = datos
        except Exception:
            pass
    return res


def unificar_identidades(force: bool = False) -> dict[str, str]:
    """Devuelve un mapa {alias_archivo: nombre_canonico}.

    Si ya existe `indices/meta/aliases.json` y `force` es False, se reutiliza.
    """
    if MAPA_PATH.exists() and not force:
        try:
            datos = json.loads(MAPA_PATH.read_text(encoding="utf-8"))
            if isinstance(datos, dict) and "mapa" in datos:
                logger.info("Mapa de aliases cargado de %s", MAPA_PATH)
                return datos["mapa"]
        except Exception:
            pass

    entidades = _cargar_indice_dir("entidades")
    emocional = _cargar_indice_dir("emocional")
    conflicto = _cargar_indice_dir("conflicto")

    if not entidades:
        logger.warning("No hay índice de entidades. No se puede unificar.")
        return {}

    huellas = [
        _huella_personaje(
            nombre,
            entidades[nombre],
            emocional.get(nombre, []),
            conflicto.get(nombre, []),
        )
        for nombre in entidades
    ]
    # Ordenar por apariciones (los pesos pesados primero, da estabilidad al LLM)
    huellas.sort(key=lambda h: -h["apariciones"])

    candidatos_str = _construir_candidatos(huellas)
    logger.info("Solicitando unificación de %d aliases al modelo...", len(huellas))
    respuesta = llamar_modelo(PROMPT.format(candidatos=candidatos_str))
    datos = extraer_json(respuesta)

    grupos = datos.get("grupos", []) if isinstance(datos, dict) else []
    if not grupos:
        logger.warning("El modelo no devolvió grupos válidos. Cada alias queda independiente.")
        mapa = {h["alias"]: h["alias"] for h in huellas}
    else:
        mapa = {}
        aliases_validos = {h["alias"] for h in huellas}
        for g in grupos:
            if not isinstance(g, dict):
                continue
            canonico = str(g.get("canonico", "")).strip() or "sin_nombre"
            for alias in g.get("aliases", []) or []:
                if alias in aliases_validos:
                    mapa[alias] = canonico

        # Fallback: cualquier alias que el modelo se haya saltado, mantenerlo como sí mismo
        for h in huellas:
            mapa.setdefault(h["alias"], h["alias"])

    # Persistir
    MAPA_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAPA_PATH.write_text(
        json.dumps({"mapa": mapa, "grupos": grupos}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    canonicos = sorted(set(mapa.values()))
    logger.info(
        "Unificación completada: %d aliases → %d entidades canónicas",
        len(mapa), len(canonicos),
    )
    return mapa
