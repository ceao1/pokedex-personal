# Las cartas que no son de los 151 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que registrar una carta fuera de los 151 avise antes de guardar y la carta tenga dónde vivir, en vez de desaparecer en silencio.

**Architecture:** Sin cambios de modelo. El binder recorre `app.pokemon`, que tiene 151 filas, así que un ejemplar cuya carta cae fuera de ese rango no aparece en ninguna consulta. Se añade una consulta que los recoja y una pantalla que los muestre.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`

## El problema, medido

Registré un Chikorita (`me02.5-008`, dex 152) contra el sistema en marcha:

```
espejado:        me02.5-008 | Chikorita | Ascended Heroes | dex 152
photo-uploaded:  200
guardar:         200
binder:          0 ejemplares de 151
```

Todo responde que sí y la carta se esfuma. Queda en la base, con su foto subida, y ninguna pantalla la muestra. Ni aviso, ni error.

## Lo que pidió el dueño

> "me gustaría darles un espacio aparte para que vivan, pero sí avisar antes"

Las dos cosas. El aviso quita la sorpresa; el espacio aparte quita la pérdida.

Esto no contradice su "no pongas secciones especiales" anterior: aquello iba de no fragmentar la grilla de los 151. Esto es lo que va **después** del binder — que es exactamente donde viven las cartas sueltas en un binder de verdad, en las últimas páginas.

## Global Constraints

- **Las tablas viven en el esquema `app`**, RLS habilitada.
- **Moneda única USD**, `Decimal` en Python, `float` solo en el borde HTTP.
- **Ningún test de la suite por defecto puede pegarle a la red.**
- **El progreso de los 151 no cambia.** Una carta fuera del proyecto no suma nada al contador, ni al "Completar el 151".
- **Copy en español**, sentence case, voz activa, **sin voseo**.
- **Sin librería de componentes ni Tailwind.** CSS Modules y los ocho tokens existentes.
- La foto propia se sirve con URL firmada; el bucket sigue privado.

---

## Task 1: El backend sabe cuáles quedan fuera

**Files:**
- Modify: `backend/src/pokedex/collection/repository.py`
- Modify: `backend/src/pokedex/api/routes/pokedex.py`
- Test: `backend/tests/collection/test_repository.py`
- Test: `backend/tests/api/test_pokedex_routes.py`

**Interfaces:**
- `collection.repository.listar_fuera_del_151(conn) -> list[dict]`
- `GET /otras-cartas` → lista de ejemplares cuya carta no pertenece a los 151

- [ ] **Step 1: Escribir los tests (que van a fallar)**

Un ejemplar queda fuera del proyecto cuando su carta **no** tiene un `dex_number` entre 1 y 151. Eso cubre tres casos distintos y los tres deben aparecer:

| Caso | Ejemplo |
|---|---|
| Pokémon de otra generación | Chikorita, dex 152 |
| Carta sin `dex_number` en el catálogo | un entrenador, o una carta cuyo `dexId` TCGdex no trae |
| Ejemplar sin carta identificada | registrado con foto y precio, sin resolver todavía |

Los tests deben cubrir además:
- un ejemplar **dentro** de los 151 no aparece en esta lista;
- una carta vendida no aparece, igual que en el binder;
- la lista trae lo necesario para dibujarla: nombre de la carta, set, número, dex si lo hay, variante, precio pagado, foto y fecha.

Y uno que fija la relación entre las dos vistas: **la suma de las dos listas es el total de ejemplares**. Ninguno puede quedar en tierra de nadie ni contarse dos veces. Ese es el test que impide que vuelva a existir el agujero negro.

- [ ] **Step 2: Escribir la consulta**

Excluye vendidas, ordena por fecha de registro descendente, y usa `left join` a `app.card` para que los ejemplares sin carta aparezcan. El filtro es `c.dex_number is null or c.dex_number not between 1 and 151`.

- [ ] **Step 3: El endpoint**

`GET /otras-cartas`, con las fotos firmadas en lote igual que `/pokedex/{dex}`. Si firmar falla, la foto va nula y la fila se devuelve igual.

- [ ] **Step 4: Correr, formatear y commitear**

---

## Task 2: El aviso antes de guardar

**Files:**
- Modify: `frontend/app/registrar/Captura.tsx`
- Modify: `frontend/app/registrar/Captura.module.css`

- [ ] **Step 1: Detectar que la carta está fuera**

Cuando se resuelve la carta —por identificación o porque el dueño escribió set y número— la respuesta del catálogo trae su `dex_number`. Si es nulo o está fuera de 1..151, la carta no es del proyecto.

- [ ] **Step 2: Avisar, no bloquear**

Un aviso claro junto al botón de guardar, antes de pulsarlo:

> **Chikorita no es de los 151.** Se guardará en *Otras cartas*, no en el binder.

Nombra el Pokémon concreto y dice **dónde va a acabar**, que es lo que el dueño necesita saber. No usa el color de error: no es un fallo, es información. El botón de guardar sigue habilitado y con el mismo texto.

Si la carta no se pudo identificar, el aviso es distinto y honesto: *"Sin identificar la carta no sabemos si es de los 151. Se guardará en Otras cartas hasta que la precises."*

- [ ] **Step 3: Verificar los dos caminos**

Con una carta de los 151, no aparece ningún aviso. Con `me02.5-008` (Chikorita), aparece. Comprobar ambos.

---

## Task 3: Las últimas páginas del binder

**Files:**
- Create: `frontend/app/otras/page.tsx`
- Create: `frontend/app/otras/Otras.tsx`
- Create: `frontend/app/otras/Otras.module.css`
- Modify: `frontend/app/lib/api.ts`, `types.ts`
- Modify: `frontend/app/binder/Rail.tsx`, `Rail.module.css`

- [ ] **Step 1: La pantalla**

Reutiliza el lenguaje del binder, no inventa otro. Los mismos bolsillos, la misma tipografía, la misma retícula — porque son cartas del mismo binder, solo que de las páginas del final.

Cada ejemplar muestra su foto propia si la tiene, y si no el arte del catálogo. Nombre de la carta, set, número, y lo que se pagó. A diferencia del binder, aquí **no hay casilleros vacíos**: solo existe lo que hay.

Vacía, la pantalla no se muestra en blanco: explica qué es este espacio y cuándo aparecerá algo aquí.

- [ ] **Step 2: El enlace desde el riel**

Debajo del contador, un enlace discreto: *"Otras cartas"* con el número entre paréntesis cuando hay alguna. **No aparece si no hay ninguna** — un enlace a una lista vacía es ruido.

Ese enlace es también el que cierra el agujero: quien registre una carta fuera del proyecto la encuentra desde la portada, sin tener que saber que existe una URL.

- [ ] **Step 3: El contador de los 151 no se mueve**

Verificar explícitamente: registrar una carta fuera del proyecto deja el contador del riel igual y no cambia "Completar el 151".

- [ ] **Step 4: Verificar de punta a punta en la IP de red**

Registrar un Chikorita, ver el aviso, guardarlo, comprobar que aparece en *Otras cartas* y que el binder no se inmuta. Borrar el ejemplar y sus fotos al terminar.

---

## Verificación del plan completo

- [ ] Registrar una carta fuera de los 151 avisa antes de guardar, nombrando el Pokémon y dónde acabará
- [ ] Esa carta aparece en *Otras cartas* con su foto
- [ ] El contador del 151 y "Completar el 151" no se mueven
- [ ] El enlace del riel no aparece cuando la lista está vacía
- [ ] La suma de las dos vistas es el total de ejemplares: ninguna carta queda invisible
- [ ] La suite pasa sin red

## Qué queda fuera

- Mover una carta de *Otras* al binder cuando se precise su identificación: hoy se corrige registrando de nuevo. Merece su propia pantalla de edición, que no existe todavía para ningún ejemplar.
- Un proyecto distinto del de los 151: el spec habla de mini-proyectos y esto no lo es.
