import json
import os
import re
import unicodedata
from pathlib import Path


def _escribir_atomico(ruta: Path, contenido: str) -> None:
    """Escribe a un .tmp y renombra. En Windows, os.replace es atómico:
    o aparece el archivo entero con el contenido nuevo, o no aparece.
    Sin esto, una interrupción a media escritura deja JSON truncados
    que rompen toda la siguiente pasada de indexación.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(contenido, encoding="utf-8")
    os.replace(tmp, ruta)


def _sanitizar_nombre(nombre: str) -> str:
    """Convierte el nombre de un personaje en un nombre de archivo seguro.

    El modelo a veces devuelve nombres con '/', '(', ')', ':', etc.
    Sin este saneamiento, Path('narrador/protagonista.json') crea una
    carpeta 'narrador' en vez de un archivo, y los datos se dispersan.
    """
    n = unicodedata.normalize("NFKC", nombre).lower().strip()
    # Sustituye TODO lo que no sea letra/dígito/guion bajo por '_'
    # Mantiene tildes y ñ (\w en modo unicode las acepta)
    n = re.sub(r"[^\w]+", "_", n, flags=re.UNICODE)
    n = re.sub(r"_+", "_", n).strip("_")
    return n or "sin_nombre"


def guardar(fragmento: dict) -> None:
    """Persiste el fragmento en todos los índices relevantes."""
    _guardar_escena(fragmento)
    _guardar_por_personaje(fragmento)
    _guardar_temporal(fragmento)


def _guardar_escena(fragmento: dict) -> None:
    ruta = Path(f"indices/escenas/{fragmento['fragmento_id']}.json")
    _escribir_atomico(ruta, json.dumps(fragmento, ensure_ascii=False, indent=2))


def _guardar_por_personaje(fragmento: dict) -> None:
    entidades = {e["nombre"]: e for e in fragmento.get("entidades", []) if isinstance(e, dict)}
    estados_por_entidad = {}
    for estado in fragmento.get("estados", []):
        nombre = estado.get("entidad", "")
        if nombre:
            estados_por_entidad[nombre] = estado

    for nombre, entidad in entidades.items():
        nombre_archivo = _sanitizar_nombre(nombre)

        # Índice emocional
        estado = estados_por_entidad.get(nombre, {})
        if estado:
            _append_json(
                Path(f"indices/emocional/{nombre_archivo}.json"),
                {
                    "personaje": nombre,
                    "fragmento_id": fragmento["fragmento_id"],
                    "capitulo": fragmento["capitulo"],
                    "palabra_inicio": fragmento["palabra_inicio"],
                    "palabra_fin": fragmento["palabra_fin"],
                    **estado
                }
            )

        # Índice entidades
        _append_json(
            Path(f"indices/entidades/{nombre_archivo}.json"),
            {
                "personaje": nombre,
                "fragmento_id": fragmento["fragmento_id"],
                "capitulo": fragmento["capitulo"],
                "palabra_inicio": fragmento["palabra_inicio"],
                "es_nueva": entidad.get("es_nueva", False),
                "tipo": entidad.get("tipo", "secundario")
            }
        )

        # Índice conflicto si el personaje está involucrado
        conflicto = fragmento.get("conflicto", {})
        involucrados = conflicto.get("entidades_involucradas", [])
        if nombre in involucrados or not involucrados:
            if conflicto.get("tipo") != "sin_conflicto":
                _append_json(
                    Path(f"indices/conflicto/{nombre_archivo}.json"),
                    {
                        "personaje": nombre,
                        "fragmento_id": fragmento["fragmento_id"],
                        "capitulo": fragmento["capitulo"],
                        "palabra_inicio": fragmento["palabra_inicio"],
                        **conflicto
                    }
                )


def _guardar_temporal(fragmento: dict) -> None:
    ruta = Path(f"indices/temporal/cap{fragmento['capitulo']:02d}.json")
    _append_json(ruta, {
        "fragmento_id": fragmento["fragmento_id"],
        "palabra_inicio": fragmento["palabra_inicio"],
        **fragmento.get("tiempo", {})
    })


def _append_json(ruta: Path, datos: dict) -> None:
    existente = []
    if ruta.exists():
        try:
            existente = json.loads(ruta.read_text(encoding="utf-8"))
            if not isinstance(existente, list):
                existente = [existente]
        except Exception:
            # Archivo corrupto de una pasada interrumpida: lo descartamos y
            # empezamos de cero. Mejor perder unas entradas que arrastrar JSON
            # inválido que rompa todo el índice.
            existente = []
    existente.append(datos)
    _escribir_atomico(ruta, json.dumps(existente, ensure_ascii=False, indent=2))
