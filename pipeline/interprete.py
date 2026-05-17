"""
Intérprete del análisis: orquesta tres fases.

  1. Integrador_Identidad — unifica aliases en entidades canónicas (LLM).
  2. Agregación — construye fichas por personaje canónico y distribuciones.
  3. Evaluador editorial — puntúa la novela criterio a criterio (LLM) y
     emite veredicto global.

Salida:
  informe.md     — informe editorial con puntuación, formato profesional.
  informe.json   — el mismo contenido en formato consumible.
"""
from __future__ import annotations

import json
import logging
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .evaluador import evaluar, CRITERIOS
from .identidad import unificar_identidades

logger = logging.getLogger(__name__)

# Estados disociativos relevantes para fantasía oscura psicológica
ESTADOS_DISOCIATIVOS = {
    "disociacion", "disociación",
    "despersonalizacion", "despersonalización",
    "anestesia_emocional",
    "hipervigilancia",
    "paralisis", "parálisis",
    "ambivalencia",
    "vacio", "vacío",
    "fatalismo",
    "resignacion", "resignación",
}


# ----------------------------------------------------------------------
# Carga
# ----------------------------------------------------------------------
def _cargar_json(ruta: Path) -> Any:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except Exception:
        return None


def _cargar_escenas() -> list[dict]:
    escenas = []
    for f in Path("indices/escenas").glob("*.json"):
        d = _cargar_json(f)
        if isinstance(d, dict):
            escenas.append(d)
    escenas.sort(key=lambda d: (d.get("capitulo", 0), d.get("palabra_inicio", 0)))
    return escenas


def _cargar_indice_dir(dir_: str) -> dict[str, list]:
    res = {}
    p = Path(f"indices/{dir_}")
    if not p.exists():
        return res
    for f in p.glob("*.json"):
        datos = _cargar_json(f)
        if isinstance(datos, list):
            res[f.stem] = datos
    return res


# ----------------------------------------------------------------------
# Agregación con aliases unificados
# ----------------------------------------------------------------------
def _agregar_personajes_canonicos(
    entidades_idx: dict[str, list],
    emocional_idx: dict[str, list],
    conflicto_idx: dict[str, list],
    mapa_aliases: dict[str, str],
) -> list[dict]:
    """Agrupa por nombre canónico (no por alias). Cada personaje canónico
    fusiona las entradas de todos sus aliases.
    """
    apariciones_por_canon = defaultdict(list)
    emocional_por_canon = defaultdict(list)
    conflicto_por_canon = defaultdict(list)
    aliases_por_canon = defaultdict(set)

    for alias, entries in entidades_idx.items():
        canon = mapa_aliases.get(alias, alias)
        apariciones_por_canon[canon].extend(entries)
        aliases_por_canon[canon].add(alias)
    for alias, entries in emocional_idx.items():
        canon = mapa_aliases.get(alias, alias)
        emocional_por_canon[canon].extend(entries)
    for alias, entries in conflicto_idx.items():
        canon = mapa_aliases.get(alias, alias)
        conflicto_por_canon[canon].extend(entries)

    fichas = []
    for canon, apariciones in apariciones_por_canon.items():
        emocional = emocional_por_canon[canon]
        conflicto = conflicto_por_canon[canon]
        aliases_lista = sorted(aliases_por_canon[canon])

        capitulos = sorted({e.get("capitulo") for e in apariciones if e.get("capitulo")})
        tipos = Counter(e.get("tipo", "?") for e in apariciones)
        tipo_predominante = tipos.most_common(1)[0][0] if tipos else "desconocido"

        primera = min(
            apariciones,
            key=lambda e: (e.get("capitulo", 0), e.get("palabra_inicio", 0)),
            default=None,
        )
        ultima = max(
            apariciones,
            key=lambda e: (e.get("capitulo", 0), e.get("palabra_inicio", 0)),
            default=None,
        )

        emos = Counter()
        intensidades = []
        cambios = 0
        disociativos = 0
        for e in emocional:
            emo = e.get("emocion_primaria")
            if emo:
                emos[emo] += 1
                if emo in ESTADOS_DISOCIATIVOS:
                    disociativos += 1
            i = e.get("intensidad_primaria")
            if isinstance(i, (int, float)):
                intensidades.append(float(i))
            if e.get("cambio_abrupto"):
                cambios += 1
        intens_media = round(statistics.mean(intensidades), 2) if intensidades else None

        tipos_conf = Counter(c.get("tipo", "?") for c in conflicto)
        resoluciones = Counter(c.get("resolucion", "?") for c in conflicto)
        contras = Counter()
        for c in conflicto:
            for inv in c.get("entidades_involucradas", []) or []:
                if inv and inv.lower() != canon.lower():
                    contras[inv] += 1

        fichas.append({
            "nombre": canon,
            "aliases": aliases_lista,
            "apariciones": len(apariciones),
            "tipo_predominante": tipo_predominante,
            "capitulos": capitulos,
            "primera_aparicion": {
                "capitulo": primera.get("capitulo") if primera else None,
                "palabra": primera.get("palabra_inicio") if primera else None,
            },
            "ultima_aparicion": {
                "capitulo": ultima.get("capitulo") if ultima else None,
                "palabra": ultima.get("palabra_inicio") if ultima else None,
            },
            "curva_emocional": {
                "emociones_frecuentes": emos.most_common(6),
                "intensidad_media": intens_media,
                "cambios_abruptos": cambios,
                "estados_disociativos": disociativos,
                "apariciones_con_emocion": len(emocional),
            },
            "conflicto": {
                "tipos": dict(tipos_conf.most_common()),
                "resoluciones": dict(resoluciones.most_common()),
                "contrapartes": dict(contras.most_common(5)),
                "total_episodios": len(conflicto),
            },
        })

    fichas.sort(key=lambda p: -p["apariciones"])
    return fichas


_NORMALIZACIONES = {
    # campo: {valor_modelo: valor_canonico}
    "modo": {
        "narración": "narracion",
        "narracion": "narracion",
        "diálogo": "dialogo",
        "dialogo": "dialogo",
        "introspección": "introspeccion",
        "introspeccion": "introspeccion",
        "mixto": "mixto",
        "?": "(no clasificado)",
    },
    "lugar": {
        "?": "(no clasificado)",
        "no determinado": "(no clasificado)",
        "desconocido": "(no clasificado)",
    },
}


def _normalizar(campo: str, valor: str) -> str:
    """Aplica el mapa de normalización para unificar variantes."""
    mapa = _NORMALIZACIONES.get(campo)
    if not mapa:
        return valor
    v = valor.strip().lower()
    return mapa.get(v, valor)


def _distribucion(escenas: list[dict], path: list[str]) -> dict[str, int]:
    c = Counter()
    campo = path[-1] if path else ""
    for d in escenas:
        cur = d
        for k in path:
            if not isinstance(cur, dict):
                cur = None
                break
            cur = cur.get(k)
        if cur is None:
            cur = "?"
        if isinstance(cur, (str, int, float, bool)):
            valor = _normalizar(campo, str(cur))
            c[valor] += 1
    return dict(c.most_common())


# ----------------------------------------------------------------------
# Render markdown
# ----------------------------------------------------------------------
def _render_markdown(datos: dict) -> str:
    r = []
    res = datos["resumen"]
    eval_ = datos["evaluacion"]
    v = eval_["veredicto"]

    # Cabecera
    r.append("# Informe editorial — análisis sobre índices procesados")
    r.append("")
    r.append(
        f"_Generado el {res['fecha_analisis']} con modelo `{res['modelo']}`. "
        f"Fragmentos analizados: {res['fragmentos']} ({res['palabras_aprox']:,} palabras "
        f"aprox., {res['num_capitulos']} capítulos)._"
    )
    r.append("")
    r.append(
        "> **Aviso de método.** Esta evaluación se construye desde los índices "
        "extraídos por el pipeline de análisis (escenas, entidades, emociones, "
        "conflicto, tiempo) más muestras puntuales del texto. No equivale a una "
        "lectura editorial completa, pero ofrece una valoración estructurada "
        "y reproducible sobre lo que el análisis automatizado ha podido capturar."
    )
    r.append("")

    # Tabla de puntuaciones
    r.append("## 1. Tabla de puntuaciones")
    r.append("")
    r.append("| Criterio | Puntuación | Peso | Ponderada | Confianza |")
    r.append("|---|---|---|---|---|")
    for letra, nombre, peso in CRITERIOS:
        c = eval_["criterios"].get(letra, {})
        p = c.get("puntuacion")
        p_str = f"{p:.1f}" if isinstance(p, (int, float)) else "—"
        pond = f"{p * peso:.2f}" if isinstance(p, (int, float)) else "—"
        r.append(
            f"| {letra}. {nombre} | {p_str} | {int(peso*100)} % | "
            f"{pond} | {c.get('confianza', '—')} |"
        )
    total = eval_["total_ponderado"]
    total_str = f"{total:.2f}" if isinstance(total, (int, float)) else "—"
    r.append(f"| **TOTAL** | | **100 %** | **{total_str}/10** | |")
    r.append("")
    # Si algún criterio no se pudo evaluar, avisar
    sin_eval = [letra for letra, _, _ in CRITERIOS
                if not isinstance(eval_["criterios"].get(letra, {}).get("puntuacion"), (int, float))]
    if sin_eval:
        r.append(
            f"> _Los criterios {', '.join(sin_eval)} no produjeron puntuación válida — "
            "el modelo no devolvió un JSON parseable pese al reintento. El total ponderado "
            "se calcula sobre los criterios restantes._"
        )
        r.append("")

    # Diagnóstico por criterio
    r.append("## 2. Diagnóstico por criterio")
    r.append("")
    for letra, nombre, _ in CRITERIOS:
        c = eval_["criterios"].get(letra, {})
        if not c:
            continue
        p = c.get("puntuacion")
        p_str = f"{p:.1f}" if isinstance(p, (int, float)) else "—"
        r.append(f"### {letra}. {nombre} — {p_str}/10")
        r.append("")
        r.append(c.get("argumento", "—"))
        if c.get("referencias"):
            r.append("")
            r.append("_Referencias usadas:_ " + "; ".join(c["referencias"]))
        if c.get("mejora") and isinstance(p, (int, float)) and p < 7:
            r.append("")
            r.append(f"**Cómo subir la nota:** {c['mejora']}")
        r.append("")

    # Mapa de problemas y fortalezas
    if v.get("problemas_mayores") or v.get("problemas_menores"):
        r.append("## 3. Mapa de problemas")
        r.append("")
        if v.get("problemas_mayores"):
            r.append("**Mayores** (degradan significativamente la experiencia lectora):")
            r.append("")
            for p in v["problemas_mayores"]:
                r.append(f"- {p}")
            r.append("")
        if v.get("problemas_menores"):
            r.append("**Menores** (pulido, no reestructuración):")
            r.append("")
            for p in v["problemas_menores"]:
                r.append(f"- {p}")
            r.append("")

    if v.get("fortalezas"):
        r.append("## 4. Fortalezas reales")
        r.append("")
        for f in v["fortalezas"]:
            r.append(f"- {f}")
        r.append("")

    # Veredicto
    r.append("## 5. Veredicto editorial")
    r.append("")
    r.append(v.get("veredicto", "—"))
    r.append("")

    # Próximos pasos
    if v.get("proximos_pasos"):
        r.append("## 6. Próximos pasos recomendados")
        r.append("")
        for i, p in enumerate(v["proximos_pasos"], 1):
            r.append(f"{i}. {p}")
        r.append("")

    # Anexo: mapa de personajes unificados (solo los relevantes; singletons al final)
    r.append("## Anexo A. Mapa de personajes (tras unificación de aliases)")
    r.append("")
    relevantes = [p for p in datos["personajes_canonicos"] if p["apariciones"] >= 2]
    singletons = [p for p in datos["personajes_canonicos"] if p["apariciones"] < 2]

    for p in relevantes:
        ce = p["curva_emocional"]
        emos = ", ".join(f"{e} ({n})" for e, n in ce["emociones_frecuentes"][:4])
        r.append(f"### {p['nombre']}")
        r.append("")
        r.append(
            f"- **Tipo:** {p['tipo_predominante']} | "
            f"**Apariciones:** {p['apariciones']} | "
            f"**Capítulos:** {', '.join(str(c) for c in p['capitulos'])}"
        )
        if len(p["aliases"]) > 1:
            r.append(
                f"- **Aliases unificados:** {', '.join(p['aliases'])}"
            )
        if ce["apariciones_con_emocion"]:
            r.append(f"- **Emociones:** {emos}")
            if ce["intensidad_media"] is not None:
                r.append(f"- **Intensidad media:** {ce['intensidad_media']}")
            if ce["estados_disociativos"]:
                r.append(f"- **Disociativos:** {ce['estados_disociativos']}")
        if p["conflicto"]["total_episodios"]:
            cf = p["conflicto"]
            tipos = ", ".join(f"{k} ({v})" for k, v in cf["tipos"].items())
            r.append(f"- **Conflicto:** {tipos}")
            if cf["contrapartes"]:
                contras = ", ".join(f"{k} ({v})" for k, v in cf["contrapartes"].items())
                r.append(f"- **Contrapartes:** {contras}")
        r.append("")

    if singletons:
        r.append(
            f"_{len(singletons)} entidades con una sola aparición — probables "
            "aliases que el integrador de identidad no consiguió unificar o "
            "personajes muy episódicos:_"
        )
        r.append("")
        r.append(", ".join(p["nombre"] for p in singletons))
        r.append("")

    # Anexo: distribuciones brutas
    r.append("## Anexo B. Distribuciones brutas")
    r.append("")
    for clave, etiqueta in [
        ("tiempo_secuencia", "Tipo de secuencia temporal"),
        ("modo", "Modo narrativo"),
        ("lugares", "Lugares"),
        ("conflicto_tipo", "Tipos de conflicto"),
        ("emociones", "Paleta emocional global"),
    ]:
        if clave not in datos["distribuciones"]:
            continue
        r.append(f"**{etiqueta}**")
        r.append("")
        for k, vv in list(datos["distribuciones"][clave].items())[:20]:
            marca = " *(disociativo)*" if clave == "emociones" and k in ESTADOS_DISOCIATIVOS else ""
            r.append(f"- {k}: {vv}{marca}")
        r.append("")

    return "\n".join(r) + "\n"


# ----------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------
def interpretar() -> None:
    escenas = _cargar_escenas()
    if not escenas:
        print("No hay fragmentos válidos en indices/escenas/. Ejecuta --indexar primero.")
        return

    entidades_idx = _cargar_indice_dir("entidades")
    emocional_idx = _cargar_indice_dir("emocional")
    conflicto_idx = _cargar_indice_dir("conflicto")

    print(f"Cargados {len(escenas)} fragmentos. Iniciando unificación de identidades...")

    # Fase 1 — Integrador_Identidad
    mapa = unificar_identidades(force=False)

    # Fase 2 — Agregación con aliases unificados
    personajes = _agregar_personajes_canonicos(
        entidades_idx, emocional_idx, conflicto_idx, mapa
    )
    print(
        f"Personajes canónicos: {len(personajes)} "
        f"(unificados desde {len(entidades_idx)} aliases)"
    )

    palabras = max((d.get("palabra_fin", 0) for d in escenas), default=0)
    fragmentos_por_capitulo = Counter(d.get("capitulo", 0) for d in escenas)
    resumen = {
        "fragmentos": len(escenas),
        "capitulos": sorted(set(fragmentos_por_capitulo)),
        "num_capitulos": len(fragmentos_por_capitulo),
        "palabras_aprox": palabras,
        "fecha_analisis": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "modelo": os.environ.get("LM_STUDIO_MODEL", "desconocido"),
    }

    distribuciones = {
        "escena_tipo": _distribucion(escenas, ["escena", "tipo"]),
        "modo": _distribucion(escenas, ["escena", "modo"]),
        "lugares": _distribucion(escenas, ["escena", "lugar"]),
        "tiempo_secuencia": _distribucion(escenas, ["tiempo", "tipo_secuencia"]),
        "tiempo_duracion": _distribucion(escenas, ["tiempo", "duracion"]),
        "conflicto_tipo": _distribucion(escenas, ["conflicto", "tipo"]),
        "emociones": dict(Counter(
            e.get("emocion_primaria", "?")
            for d in escenas
            for e in d.get("estados", []) if isinstance(e, dict)
        ).most_common()),
    }

    agregados = {
        "resumen": resumen,
        "distribuciones": distribuciones,
        "personajes_canonicos": personajes,
    }

    # Fase 3 — Evaluación editorial criterio por criterio
    print("Lanzando evaluación editorial (7 criterios + veredicto)...")
    evaluacion = evaluar(agregados, dict(fragmentos_por_capitulo))
    print(
        f"Puntuación total: {evaluacion['total_ponderado']}/10 "
        f"(con {evaluacion['muestras_usadas']} muestras de texto)"
    )

    datos = {**agregados, "evaluacion": evaluacion}

    Path("informe.json").write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    Path("informe.md").write_text(_render_markdown(datos), encoding="utf-8")

    print(f"\ninforme.md     ({Path('informe.md').stat().st_size:,} bytes)")
    print(f"informe.json   ({Path('informe.json').stat().st_size:,} bytes)")
