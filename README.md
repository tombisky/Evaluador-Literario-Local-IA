# Arquitectura de comprensión literaria

Pipeline multiagente local para extraer comprensión narrativa de manuscritos largos y producir una valoración editorial estructurada. Cada fragmento del texto pasa por varios sensores especializados (escena, entidades, emociones, conflicto, tiempo), los resultados se cruzan en índices por personaje y, finalmente, un evaluador editorial puntúa la novela criterio a criterio.

Todo corre **en local** sobre [LM Studio](https://lmstudio.ai). El manuscrito nunca sale de la máquina.

---

## Qué hace

Dado un manuscrito dividido en capítulos `.md` dentro de `ficheros/`, el sistema:

1. **Indexa** cada fragmento (~250 palabras) con cinco sensores que escriben índices JSON estructurados:
   - `escenas/` — tipo de escena, lugar, modo (narración, diálogo, introspección).
   - `entidades/` — personajes detectados con tipo (protagonista / secundario / mencionado).
   - `emocional/` — taxonomía Plutchik expandida con estados disociativos (`hipervigilancia`, `disociacion`, `anestesia_emocional`, `ambivalencia`, `vacio`…), por personaje y por fragmento.
   - `conflicto/` — interpersonal, interno, persona_entorno; intensidad y resolución.
   - `temporal/` — presente_narrativo, analepsis, prolepsis, iterativo, elipsis, por capítulo.
2. **Unifica identidades**: un integrador llama al LLM para fusionar aliases del mismo personaje (`yo`, `narrador`, `narrador_protagonista` → una sola entidad canónica).
3. **Evalúa editorialmente** con la rúbrica clásica de agencia literaria (Voz, Estructura, Personajes, Prosa, Mundo, Tensión, Originalidad), ponderada. Cada criterio recibe solo los datos relevantes; criterios de prosa y voz reciben además muestras literales del texto.
4. Genera **`informe.md`** (legible) e **`informe.json`** (consumible por programa) con la puntuación, diagnóstico criterio a criterio, mapa de problemas, fortalezas, veredicto y próximos pasos.

---

## Arquitectura

```
┌────────────────────────────────────────────────────────────┐
│  main.py  (orquestador)                                    │
│  · trocea capítulos en fragmentos                           │
│  · gestiona reset, estado, reanudación                      │
└──────────────┬─────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────┐
│  Sensores (1 llamada al LLM cada uno, por fragmento)        │
│                                                            │
│  detector_escena    sensor_entidad    sensor_emocion       │
│  sensor_conflicto   sensor_tiempo                          │
└──────────────┬─────────────────────────────────────────────┘
               │ JSON estructurado por sensor
               ▼
┌────────────────────────────────────────────────────────────┐
│  integrador.py + persistor.py                              │
│  · agrega capas en un único objeto por fragmento            │
│  · escribe atómicamente en indices/*/                       │
└──────────────┬─────────────────────────────────────────────┘
               │
               ▼
┌────────────────────────────────────────────────────────────┐
│  interprete.py (orquesta interpretación)                    │
│                                                            │
│   1. identidad.py     — unifica aliases con el LLM         │
│   2. agregación       — fichas por personaje canónico       │
│   3. evaluador.py     — 7 criterios + veredicto (LLM)      │
└──────────────┬─────────────────────────────────────────────┘
               │
               ▼
        informe.md  +  informe.json
```

---

## Requisitos

- **Python 3.10+**
- **LM Studio** instalado, con su servidor local activo en `http://localhost:1234`
- Un modelo de instrucción cargado en LM Studio. Probado con:
  - `qwen2.5-7b-instruct` (Q5_K_M) — recomendado, equilibrio velocidad/calidad
  - `gemma-3-12b-it` (Q4_K_M) — mayor capacidad si dispones de ~10 GB de VRAM
  - Cualquier modelo de instrucción ≥7B en español funciona si cabe en tu GPU

- **VRAM mínima recomendada:** 8 GB. Con 12 GB cabe holgado un 7B Q5 o un 12B Q4. Para 31B+ necesitas 20 GB+ o aceptar offload a CPU (muy lento para esta carga de trabajo).

- **Dependencia Python:** una única, `openai` (el SDK habla con la API OpenAI-compatible de LM Studio).

---

## Instalación

```bash
git clone https://github.com/<tu-usuario>/arquitectura-de-comprension-literaria.git
cd arquitectura-de-comprension-literaria
pip install openai
```

Arranca LM Studio, carga un modelo y abre el servidor (`Developer → Start Server`).

---

## Configuración

Edita las **dos líneas** del bloque de configuración al principio de `main.py`:

```python
MODELO_LLM = "qwen2.5-7b-instruct"
LM_STUDIO_URL = "http://localhost:1234/v1"
```

El identificador exacto del modelo cargado lo obtienes con:

```bash
curl http://localhost:1234/v1/models
```

Alternativamente puedes sobrescribir con variables de entorno (`LM_STUDIO_MODEL`, `LM_STUDIO_BASE_URL`, `LM_STUDIO_API_KEY`), pero el código en `main.py` tiene prioridad.

---

## Uso

```bash
# Procesa todos los .md de ficheros/ con reset previo automático
python main.py --indexar

# Indexación incremental (mantiene índices existentes)
python main.py --indexar --noreset

# Genera informe editorial a partir de los índices ya procesados
python main.py --interpretar

# Borra estado.json e indices/ sin indexar
python main.py --reset

# Muestra progreso actual
python main.py --estado
```

**Flujo típico**

1. Mete los capítulos como `1 - Titulo.md`, `2 - Titulo.md`, ... en `ficheros/`.
2. `python main.py --indexar` (espera ~2-4 horas para 40 capítulos con un 7B; depende de tu GPU).
3. `python main.py --interpretar` (1-2 minutos: 9 llamadas al LLM).
4. Abre `informe.md`.

---

## Estructura del proyecto

```
.
├── main.py                    # orquestador y CLI
├── ficheros/                  # capítulos del manuscrito (.md, fuente)
├── ficheros_total/            # copia de respaldo del manuscrito completo
├── indices/                   # generado: índices por sensor
│   ├── escenas/
│   ├── entidades/
│   ├── emocional/
│   ├── conflicto/
│   ├── temporal/
│   └── meta/aliases.json      # mapa alias → entidad canónica
├── pipeline/
│   ├── base.py                # cliente LM Studio + parseo JSON
│   ├── detector_escena.py     # tipo, lugar, modo
│   ├── sensor_entidad.py      # personajes humanos
│   ├── sensor_emocion.py      # Plutchik expandido + estados disociativos
│   ├── sensor_conflicto.py    # tipo, intensidad, resolución
│   ├── sensor_tiempo.py       # presente / analepsis / prolepsis / iterativo / elipsis
│   ├── integrador.py          # une las cinco capas
│   ├── persistor.py           # escritura atómica + sanitización de nombres
│   ├── identidad.py           # integrador_identidad (unifica aliases)
│   ├── evaluador.py           # rúbrica editorial con LLM
│   └── interprete.py          # orquesta identidad → agregación → evaluación
├── estado.json                # frag_ids ya procesados (reanudación)
├── informe.md                 # generado: informe editorial humano
├── informe.json               # generado: mismo informe estructurado
├── auditar.py                 # script de auditoría de los índices
└── README.md
```

---

## Garantías de robustez

El persistor escribe siempre de forma atómica (`.tmp` + `os.replace`), así que una interrupción nunca deja JSON truncados. Si por cualquier motivo un archivo de índice queda corrupto, `_append_json` lo detecta y empieza de cero en ese personaje en lugar de propagar la corrupción.

El estado se persiste tras cada fragmento, así que indexaciones largas se reanudan sin pérdida si las cortas con Ctrl+C.

Por defecto, `--indexar` siempre hace reset previo de `estado.json` e `indices/`. Esto evita contaminar los índices con datos de pasadas anteriores (típicamente, salidas de modelos distintos con formatos ligeramente distintos). Usa `--noreset` cuando tengas la certeza de que quieres preservar lo anterior.

---

## Limitaciones conocidas

- **El integrador de identidad es perfectible**: el LLM agrupa la mayoría de aliases del narrador, pero a veces deja entidades sueltas que evidentemente son la misma persona (por ejemplo, no funde el `narrador` con el nombre propio cuando el modelo no tiene pista contextual). El mapa generado vive en `indices/meta/aliases.json` y puedes editarlo a mano si quieres forzar agrupaciones; se preservará en ejecuciones posteriores hasta que hagas `--reset`.
- **`detector_escena` clasifica todo como `presente_narrativo`** con los modelos ≤7B probados. El `sensor_tiempo` sí distingue analepsis, así que la información temporal real está en el índice temporal, no en el de escenas. Está pendiente de afinar el prompt.
- **Voz narrativa y Prosa** son criterios difíciles de evaluar desde índices agregados. El evaluador les inyecta muestras literales del texto para compensar, pero la confianza para esos criterios suele ser media-baja.
- **El sistema está optimizado para narrativa en primera persona en español de España**. Funcionará con otros idiomas, pero los prompts hablan español y la taxonomía emocional incluye matices culturales y traduccionales específicos.

---

## Roadmap

- [x] Pipeline de sensores
- [x] Persistencia atómica
- [x] Integrador_Identidad con LLM
- [x] Evaluador editorial con rúbrica ponderada
- [ ] Refinar prompt del detector_escena para que distinga analepsis
- [ ] Modo `--consultar`: preguntas en lenguaje natural sobre el manuscrito
- [ ] Edición interactiva del mapa de aliases (`--identidad`)
- [ ] Paralelización opcional de sensores por fragmento

---

## Licencia

MIT.

---

## Notas

Este sistema nació como herramienta de autoanálisis para una novela propia (fantasía oscura psicológica en primera persona). Se publica por si resulta útil a otros autores, agencias o lectores editoriales que quieran consolidar comprensión literaria desde texto largo sin enviar el manuscrito a una API remota.
