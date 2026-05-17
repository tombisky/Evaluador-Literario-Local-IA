"""Auditoría de los índices. Solo lee, no modifica nada.

Uso:
    python auditar.py
"""
import json
import glob
import os
from collections import Counter
from datetime import datetime


def main() -> None:
    print("=" * 60)
    print(" AUDITORÍA DE ÍNDICES")
    print("=" * 60)

    # 1. Estado
    if os.path.exists("estado.json"):
        try:
            d = json.load(open("estado.json", encoding="utf-8"))
            print(f"\n[1] estado.json: {len(d)} fragmentos procesados")
            if d:
                print(f"    rango: {min(d)} → {max(d)}")
        except Exception as e:
            print(f"\n[1] estado.json: CORRUPTO ({e})")
    else:
        print("\n[1] estado.json: no existe")

    # 2. Conteo por carpeta
    print("\n[2] Archivos por índice")
    for sub in ("escenas", "emocional", "entidades", "conflicto", "temporal", "meta"):
        ruta = f"indices/{sub}"
        if os.path.isdir(ruta):
            archivos = [f for f in os.listdir(ruta) if f.endswith(".json")]
            tmps = [f for f in os.listdir(ruta) if f.endswith(".tmp")]
            extra = f", {len(tmps)} .tmp residuales" if tmps else ""
            print(f"    {sub}: {len(archivos)} json{extra}")
        else:
            print(f"    {sub}: carpeta no existe")

    # 3. Validez JSON
    rotos = []
    total = 0
    for f in glob.glob("indices/**/*.json", recursive=True):
        total += 1
        try:
            json.load(open(f, encoding="utf-8"))
        except Exception as e:
            rotos.append((f, str(e)[:60]))

    pct = (total - len(rotos)) * 100 / total if total else 0
    print(f"\n[3] Validez JSON: {total - len(rotos)}/{total} válidos ({pct:.1f} %)")
    if rotos:
        print("    Muestra de rotos:")
        for f, e in rotos[:5]:
            print(f"      {f}: {e}")

    # 4. Análisis de escenas
    print("\n[4] Análisis de escenas")
    escenas = []
    for f in glob.glob("indices/escenas/*.json"):
        try:
            escenas.append(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass

    print(f"    Escenas válidas: {len(escenas)}")
    if escenas:
        print(f"    tipo: {dict(Counter(d['escena'].get('tipo','?') for d in escenas))}")
        print(f"    modo: {dict(Counter(d['escena'].get('modo','?') for d in escenas))}")
        emos = Counter()
        for d in escenas:
            for e in d.get("estados", []):
                if isinstance(e, dict):
                    emos[e.get("emocion_primaria", "?")] += 1
        print(f"    top emociones: {emos.most_common(8)}")
        tiempos = Counter(d.get("tiempo", {}).get("tipo_secuencia", "?") for d in escenas)
        print(f"    tiempo: {dict(tiempos)}")
        conflictos = Counter(d.get("conflicto", {}).get("tipo", "?") for d in escenas)
        print(f"    conflicto: {dict(conflictos)}")

    # 5. Entidades creadas
    print("\n[5] Archivos de personajes en indices/entidades/")
    if os.path.isdir("indices/entidades"):
        for f in sorted(os.listdir("indices/entidades")):
            if f.endswith(".json"):
                print(f"    {f}")

    # 6. Rango mtime
    print("\n[6] Rango temporal de la última pasada")
    mtimes = []
    for f in glob.glob("indices/**/*.json", recursive=True):
        mtimes.append(os.path.getmtime(f))
    if mtimes:
        ini = datetime.fromtimestamp(min(mtimes)).strftime("%Y-%m-%d %H:%M:%S")
        fin = datetime.fromtimestamp(max(mtimes)).strftime("%Y-%m-%d %H:%M:%S")
        print(f"    primer archivo: {ini}")
        print(f"    último archivo: {fin}")


if __name__ == "__main__":
    main()
