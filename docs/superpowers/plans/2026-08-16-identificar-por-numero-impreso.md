# Identificar por lo impreso en la carta, no por el nombre del set — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que una foto de una carta se identifique sola cuando el catálogo puede confirmarla, en vez de rechazarla porque el modelo no supo nombrar el set.

**Architecture:** El resolutor deja de apoyarse en `set_name` y pasa a apoyarse en lo que está **impreso junto al número**: el código del set y el número `NNN/TTT`. El código identifica el set sin ambigüedad; el denominador es el respaldo cuando no lo hay; la especie y el `dexId` confirman. La duda del modelo deja de ser un veto y pasa a ser una señal entre varias.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md` §5.2 y §6.2

## La evidencia que motiva el cambio

El dueño fotografió dos cartas suyas de Ascended Heroes. El sistema rechazó las dos. Esto es lo que había leído el modelo, y lo que resultó ser cierto:

| Carta | Gemini leyó | La carta real |
|---|---|---|
| Drampa | `176/217`, especie Drampa, dex 780, `set_name: null`, `needs_review: true`, conf. 0.8 | `me02.5-176` — Drampa, Ascended Heroes, `dexId [780]` |
| Groudon | `108/217`, especie Groudon, dex 383, `set_name: null`, `needs_review: true`, conf. 0.5 | `me02.5-108` — Groudon, Ascended Heroes, `dexId [383]` |

**Acertó todo lo verificable en ambas.** `217` identifica un único set entre los 218 del catálogo. Las dos eran resolubles con certeza y se descartaron.

### El código de set, que es la señal más fuerte

Lo señaló el dueño: junto al número va impreso el código del set — en sus cartas, `ASC`. Verificado contra el catálogo:

- TCGdex lo expone como `abbreviation.official` en el detalle de cada set (`me02.5` → `ASC`).
- **188 de los 218 sets lo tienen, y las 188 abreviaturas son únicas: cero colisiones.** `BS` es Base Set, `JU` Jungle, `FO` Fossil.
- Los 30 sin abreviatura son los antiguos, donde la carta física tampoco la lleva.

Es un identificador perfecto cuando existe, y muy superior al denominador, único solo en 62 de 218. Pasa a ser la vía principal.

Dos errores de diseño, los dos míos:

1. **Depender de `set_name`** es pedirle al modelo que *recuerde* un nombre en vez de *leer* lo impreso. El código y el número están impresos en la carta; el nombre del set, muchas veces, ni aparece.
2. **Vetar por `needs_review`** descarta la lectura aunque el catálogo la confirme por tres vías independientes. La autoevaluación del modelo es información útil, no una autoridad por encima de los hechos.

## Global Constraints

- **La respuesta del modelo nunca se acepta sola.** Lo que cambia es *qué* la confirma: antes el nombre del set, ahora el cruce contra el catálogo.
- **La variante sigue siendo del humano.** El modelo no la propone; el precio depende de ella.
- **El endpoint no escribe en `owned_copy`.** Propone; el humano dispone.
- **La llave nunca sale del backend.**
- **Ningún test de la suite por defecto pega a la red.** Los reales llevan `@pytest.mark.contract`.
- **Cada llamada real cuesta dinero del dueño.** Sin bucles de reintento; el desempate por imágenes solo cuando de verdad hace falta.
- **Copy en español**, sentence case, sin voseo.

---

## Task 1: El catálogo sabe buscar sets por su código y por su tamaño

**Files:**
- Modify: `backend/src/pokedex/catalog/ports.py`, `tcgdex.py`, `service.py`
- Test: `backend/tests/catalog/test_tcgdex.py`, `test_service.py`

**Interfaces:**
- `CatalogPort.list_sets() -> list[SetRef]` con `SetRef(id, name, total, abbreviation)` — si ya existe, ampliarlo
- `CatalogService.set_por_codigo(codigo: str) -> SetRef | None`, cacheado
- `CatalogService.sets_por_total(total: int) -> list[SetRef]`, cacheado

- [ ] **Step 1: Tests**

`set_por_codigo("ASC")` devuelve `me02.5`; `set_por_codigo("asc")` también, sin distinguir mayúsculas; un código inexistente devuelve `None`. `sets_por_total(217)` devuelve exactamente un set. `sets_por_total(102)` devuelve varios — hay tamaños repetidos y devolver varios es correcto. La lista se pide **una sola vez** aunque se consulten varios códigos y totales.

Ojo: la abreviatura vive en el **detalle** de cada set, no en el listado. Traer los 218 detalles en cada arranque sería caro; construir el índice una vez y cachearlo, o resolver bajo demanda y memorizar. La decisión es tuya, pero documenta cuál tomaste y por qué.

- [ ] **Step 2: Implementar**

`GET /v2/en/sets` devuelve 218 entradas con `{id, name, cardCount}` — **sin** la abreviatura, que solo aparece en `GET /v2/en/sets/{id}` bajo `abbreviation.official`. Cachear en memoria como ya hace `list_set_cards`.

---

## Task 2: Resolver por lo impreso en la carta

Esta es la task que arregla el problema.

**Files:**
- Modify: `backend/src/pokedex/recognition/resolver.py`
- Test: `backend/tests/recognition/test_resolver.py`

- [ ] **Step 1: Pedir y parsear lo impreso**

El prompt de Gemini gana un campo: `set_code`, el código impreso junto al número (`ASC`, `BS`, `JU`). Se le dice que copie lo que ve y que ponga `null` si no lo distingue — nunca que lo deduzca del nombre del set, porque entonces vuelve a ser memoria en vez de lectura.

El número se parsea con tolerancia: `176/217`, `002/217`, `4/102`, con espacios alrededor de la barra. Sin barra, se conserva el numerador y el denominador queda nulo.

- [ ] **Step 2: La cascada de resolución**

En este orden, parando en cuanto haya una única candidata:

1. **Por código de set.** `set_code` contra `abbreviation.official`, sin distinguir mayúsculas. Es único, así que da un solo set: se busca la carta `NNN` y se **confirma** (ver abajo).
2. **Por denominador.** Sets cuyo total oficial sea `TTT`. Para cada uno, buscar la carta `NNN`. Quedarse con las que confirmen.
3. **Por `set_name`**, si el modelo lo dio y resuelve a un set conocido. Sigue siendo una señal válida cuando existe.
4. **Sin resolver**, con motivo explícito.

Cuando el código y el denominador apunten a sets distintos, **no se elige**: es una contradicción y va a revisión, igual que cuando el `dexId` contradice la especie.

- [ ] **Step 3: Qué cuenta como confirmación**

Una candidata se acepta si la carta existe en `(set, número)` **y al menos una** de estas coincide, sin contradecir la otra:

- el `dexId` de la carta coincide con el `dex_number` que leyó el modelo;
- el nombre de la carta coincide con el nombre leído o con la especie, comparando sin distinguir mayúsculas ni acentos y tolerando posesivos de entrenador (`Erika's Gloom` ≡ `Gloom`) y sufijos (`ex`, `V`, `VMAX`, `GX`).

**Contradicción explícita = rechazo.** Si el `dexId` de la carta es 25 y el modelo leyó 44, no se acepta aunque el nombre se parezca. Dos señales que se contradicen no son una confirmación — la misma regla que ya rige la validación de especie.

- [ ] **Step 4: `needs_review` deja de ser veto**

La autoevaluación del modelo y su `confidence` se conservan en la respuesta y se muestran al humano, pero **no impiden proponer** una carta que el catálogo confirmó. Lo que impide proponer es la falta de confirmación.

Cuando el modelo dudaba y el catálogo confirma, el motivo debe decirlo, para que la pantalla pueda ser honesta: algo como *"el modelo dudó, pero el número coincide con una carta real"*.

- [ ] **Step 5: Los casos de test**

Escribir uno por fila, con un catálogo falso:

| Entrada | Resultado |
|---|---|
| `ASC`, `176/217`, Drampa, dex 780 | resuelve por el código, sin mirar el denominador |
| sin código, `176/217`, Drampa, dex 780 | resuelve por el denominador |
| `108/217`, Groudon, dex 383 | resuelve |
| código `ASC` pero denominador de otro set | rechaza: señales contradictorias |
| código que no existe en el catálogo | cae al denominador |
| denominador que casa con tres sets, uno solo con esa carta | resuelve |
| denominador que casa con tres sets, dos con esa carta | no resuelve solo: candidatas para desempate |
| el número existe pero el `dexId` contradice la especie | rechaza, motivo explícito |
| sin denominador y con `set_name` válido | resuelve por el nombre |
| sin denominador y sin `set_name` | no resuelve |
| `Erika's Gloom` contra una carta llamada `Erika's Gloom`, especie `Gloom` | resuelve |

Los dos primeros son los casos reales del dueño y deben quedar nombrados como tales en el test.

---

## Task 3: Desempate por imagen, solo cuando hace falta

**Files:**
- Modify: `backend/src/pokedex/recognition/ports.py`, `gemini.py`, `resolver.py`
- Test: `backend/tests/recognition/test_desempate.py`

- [ ] **Step 1: El puerto**

`RecognitionPort.elegir_entre(foto: bytes, candidatas: list[CandidataImagen]) -> str | None`, donde cada candidata lleva su `card_id` y su imagen. Devuelve el `card_id` elegido o `None` si no lo tiene claro.

- [ ] **Step 2: Cuándo se invoca**

Solo cuando la Task 2 deja **entre 2 y 5** candidatas confirmadas. Con una, ya está. Con más de cinco, no se desempata: se devuelven para revisión manual, porque mandar diez imágenes por identificación no compensa.

- [ ] **Step 3: El prompt**

La foto del dueño primero, luego las candidatas numeradas con su `card_id`. Se le pide que devuelva el `card_id` de la que coincide, o `null` si ninguna coincide claramente. Se le dice explícitamente que **prefiera `null` a adivinar**: un desempate equivocado es peor que pedir ayuda al humano, porque nadie lo revisaría.

- [ ] **Step 4: El resultado se valida igual**

El `card_id` que devuelva debe estar entre las candidatas que se le pasaron. Cualquier otra cosa se descarta como alucinación y se cae a revisión manual.

- [ ] **Step 5: Test de contrato**

Uno solo, marcado `contract`: dos cartas reales del mismo Pokémon en sets distintos, y comprobar que elige la correcta.

---

## Task 4: Guardar lo que se sabe aunque falte la carta

Lo que el dueño pidió: *"permite que el set quede vacío, si es posible identificarlo bien, si no no pasa nada"*.

**Files:**
- Create: `supabase/migrations/<ts>_owned_copy_dex_number.sql`
- Modify: `backend/src/pokedex/collection/models.py`, `repository.py`
- Modify: `backend/src/pokedex/wishlist/repository.py`
- Test: `backend/tests/collection/test_repository.py`

- [ ] **Step 1: La columna**

`app.owned_copy.dex_number integer null`, con `check (dex_number is null or dex_number between 1 and 151)`. Es el casillero al que cuelga el ejemplar cuando su carta no se conoce o no tiene `dexId`.

- [ ] **Step 2: Las consultas usan las dos vías**

Donde hoy se lee `card.dex_number`, pasa a leerse `coalesce(card.dex_number, owned_copy.dex_number)`. La carta manda cuando existe; el valor propio del ejemplar es el respaldo.

Eso vale para `owned_count`, para la ficha por Pokémon y para el reparto entre el binder y *Otras cartas*.

- [ ] **Step 3: El test que impide el agujero**

El que ya existe —la suma de las dos vistas es el total de ejemplares— debe seguir pasando con un ejemplar que tenga `dex_number` propio y ninguna carta. Añadir ese caso al fixture.

- [ ] **Step 4: Un ejemplar sin carta pero con especie cuelga de su casillero**

Test: crear un ejemplar con `dex_number = 44` y sin `card_id`, y comprobar que el casillero 44 lo cuenta y que **no** aparece en *Otras cartas*.

---

## Verificación del plan completo

- [ ] Las dos fotos reales del dueño (Drampa `176/217` y Groudon `108/217`) se identifican solas
- [ ] Una lectura que el catálogo contradice se sigue rechazando
- [ ] El desempate por imagen solo se invoca con 2 a 5 candidatas
- [ ] Un ejemplar con especie confirmada y sin carta cuelga de su casillero
- [ ] La suma de las dos vistas sigue siendo el total de ejemplares
- [ ] La suite pasa sin red; los contratos pasan con red

## Qué queda fuera

- Detectar la variante por foto: excluido por el spec, y el precio depende de acertarla.
- Reintentos automáticos de identificación: una llamada por foto; el dueño puede repetirla.
- Corregir la carta de un ejemplar ya guardado: necesita una pantalla de edición que no existe para ningún campo todavía.
