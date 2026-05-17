"""
Sistema de Interpretación Narrativa — Pipeline Secuencial v2
Uso:
  python main.py --indexar              # reset + indexa ficheros/ (por defecto)
  python main.py --indexar --noreset    # indexación incremental (mantiene índices)
  python main.py --interpretar          # genera informe.md y informe.json
  python main.py --estado               # muestra progreso
  python main.py --reset                # solo reset, sin indexar
  python main.py --consultar            # modo consulta (pendiente)
"""
import argparse
import json
import logging
import os
import re
import shutil
from pathlib import Path

# =====================================================================
# CONFIGURACIÓN DEL MODELO
# =====================================================================
# Edita estas dos constantes según el modelo cargado en LM Studio.
# El identificador exacto del modelo se obtiene con:
#   curl http://localhost:1234/v1/models
MODELO_LLM = "qwen2.5-7b-instruct"
LM_STUDIO_URL = "http://localhost:1234/v1"
# =====================================================================

# Estos os.environ DEBEN setearse antes del import de pipeline.base,
# porque ahí se crea el cliente OpenAI con esa URL y se fija MODELO.
os.environ["LM_STUDIO_MODEL"] = MODELO_LLM
os.environ["LM_STUDIO_BASE_URL"] = LM_STUDIO_URL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)

from pipeline.base import MODELO
from pipeline.detector_escena import detectar as detectar_escena
from pipeline.sensor_entidad import detectar as detectar_entidades
from pipeline.sensor_emocion import detectar as detectar_emociones
from pipeline.sensor_conflicto import detectar as detectar_conflicto
from pipeline.sensor_tiempo import detectar as detectar_tiempo
from pipeline.integrador import integrar
from pipeline.persistor import guardar
from pipeline.interprete import interpretar

ESTADO_FILE = Path("estado.json")
TAM_FRAGMENTO = 250
OVERLAP = 30


def cargar_estado() -> set:
    if ESTADO_FILE.exists():
        return set(json.loads(ESTADO_FILE.read_text(encoding="utf-8")))
    return set()


def guardar_estado(procesados: set) -> None:
    ESTADO_FILE.write_text(json.dumps(list(procesados)), encoding="utf-8")


def fragmentar(texto: str, offset: int) -> list:
    palabras = texto.split()
    fragmentos = []
    pos = 0
    while pos < len(palabras):
        fin = min(pos + TAM_FRAGMENTO, len(palabras))
        fragmentos.append({
            "texto": " ".join(palabras[pos:fin]),
            "palabra_inicio": offset + pos,
            "palabra_fin": offset + fin
        })
        pos += TAM_FRAGMENTO - OVERLAP
    return fragmentos


def procesar_fragmento(frag_id: str, texto: str, cap: int, p_ini: int, p_fin: int) -> dict:
    logger = logging.getLogger("pipeline")
    logger.debug("Procesando %s", frag_id)

    escena = detectar_escena(texto)
    entidades = detectar_entidades(texto, escena)
    estados = detectar_emociones(texto, entidades)
    conflicto = detectar_conflicto(texto, entidades, estados)
    tiempo = detectar_tiempo(texto)

    return integrar(frag_id, cap, p_ini, p_fin, escena, entidades, estados, conflicto, tiempo)


def indexar():
    logger = logging.getLogger("orquestador")
    carpeta = Path("ficheros")
    archivos = sorted(
        carpeta.glob("*.md"),
        key=lambda x: int("".join(filter(str.isdigit, x.stem.split("-")[0].strip())) or "0")
    )
    if not archivos:
        print("No se encontraron archivos MD en ficheros/")
        return

    procesados = cargar_estado()
    offset = 0
    total_fragmentos = 0
    total_errores = 0

    print(f"\n{'='*50}")
    print(f"  Indexación — {len(archivos)} capítulos")
    print(f"  Modelo: {MODELO} | Fragmentos ~{TAM_FRAGMENTO} palabras")
    print(f"{'='*50}\n")

    for i, archivo in enumerate(archivos, 1):
        texto = archivo.read_text(encoding="utf-8")
        # Limpiar markdown
        texto_limpio = re.sub(r"\*+", "", texto)
        texto_limpio = re.sub(r"#{1,6}\s", "", texto_limpio)

        fragmentos = fragmentar(texto_limpio, offset)
        offset += len(texto_limpio.split())

        cap_procesados = 0
        cap_errores = 0

        logger.info(
            "Capítulo %d/%d: %s — %d fragmentos",
            i, len(archivos), archivo.stem, len(fragmentos)
        )

        for frag in fragmentos:
            frag_id = f"frag{frag['palabra_inicio']:06d}"

            # Reanudación: saltar fragmentos ya procesados
            if frag_id in procesados:
                continue

            try:
                resultado = procesar_fragmento(
                    frag_id, frag["texto"], i,
                    frag["palabra_inicio"], frag["palabra_fin"]
                )
                guardar(resultado)
                procesados.add(frag_id)
                guardar_estado(procesados)
                cap_procesados += 1
                total_fragmentos += 1
            except Exception as e:
                logger.error("Error en %s: %s", frag_id, e)
                cap_errores += 1
                total_errores += 1

        entidades_cap = set()
        for frag in fragmentos:
            frag_id = f"frag{frag['palabra_inicio']:06d}"
            p = Path(f"indices/escenas/{frag_id}.json")
            if p.exists():
                try:
                    datos = json.loads(p.read_text(encoding="utf-8"))
                    for e in datos.get("entidades", []):
                        if isinstance(e, dict):
                            entidades_cap.add(e.get("nombre", ""))
                except Exception:
                    pass

        logger.info(
            "  → %d procesados, %d errores, entidades: %s",
            cap_procesados, cap_errores,
            ", ".join(sorted(entidades_cap)) or "ninguna"
        )

    print(f"\n{'='*50}")
    print(f"  Completado")
    print(f"  Fragmentos procesados: {total_fragmentos}")
    print(f"  Errores: {total_errores}")
    print(f"  Índices en: indices/")
    print(f"{'='*50}\n")


def mostrar_estado():
    procesados = cargar_estado()
    print(f"Fragmentos procesados: {len(procesados)}")
    for dim in ["escenas", "emocional", "entidades", "conflicto", "temporal"]:
        p = Path(f"indices/{dim}")
        if p.exists():
            archivos = list(p.glob("*.json"))
            print(f"  {dim}: {len(archivos)} archivos")


CARPETAS_INDICE = [
    "indices/escenas", "indices/emocional", "indices/entidades",
    "indices/conflicto", "indices/temporal", "indices/meta"
]


def _resetear() -> None:
    """Borra estado.json y todas las carpetas de índices, dejándolas vacías."""
    if ESTADO_FILE.exists():
        ESTADO_FILE.unlink()
    for d in CARPETAS_INDICE:
        p = Path(d)
        if p.exists():
            shutil.rmtree(p)
        p.mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--indexar", action="store_true",
                        help="Procesa ficheros/ con reset previo por defecto")
    parser.add_argument("--noreset", action="store_true",
                        help="Con --indexar: no resetea, hace indexación incremental")
    parser.add_argument("--interpretar", action="store_true",
                        help="Genera informe.md e informe.json desde los índices")
    parser.add_argument("--consultar", action="store_true",
                        help="(Pendiente) Modo consulta interactivo")
    parser.add_argument("--estado", action="store_true",
                        help="Muestra el progreso de indexación")
    parser.add_argument("--reset", action="store_true",
                        help="Solo reset, sin indexar")
    args = parser.parse_args()

    # Asegurar estructura de carpetas
    for d in CARPETAS_INDICE:
        Path(d).mkdir(parents=True, exist_ok=True)

    if args.reset:
        _resetear()
        print("Estado e índices reseteados.")
    elif args.indexar:
        if not args.noreset:
            _resetear()
            print("Reset previo aplicado. (Usa --noreset para indexación incremental.)")
        indexar()
    elif args.interpretar:
        interpretar()
    elif args.estado:
        mostrar_estado()
    elif args.consultar:
        print("Modo consulta pendiente de implementar.")
    else:
        parser.print_help()
