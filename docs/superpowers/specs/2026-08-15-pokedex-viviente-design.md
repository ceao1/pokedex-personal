# Diseño técnico — Pokédex Viviente

**Autor:** Carlos · **Fecha:** 2026-08-15 · **Estado:** Aprobado para planificación
**Antecede a:** `PRD_Coleccion_Pokedex_151.md` (v0.2)

Este documento resuelve las decisiones que el PRD dejó abiertas y fija el diseño del MVP. Donde contradice al PRD, manda este documento; la sección [Cambios respecto al PRD](#13-cambios-respecto-al-prd) lista las diferencias.

---

## 1. Alcance

Aplicación web personal, un solo usuario, para registrar la colección física de cartas Pokémon en inglés. La app responde cuatro preguntas: qué tengo, cuánto gasté, dónde está guardada cada carta y cuánto me falta para completar el Pokédex de los 151.

**Fuera del MVP:** multiusuario, ventas, grading automático, cartas en japonés, histórico de precios, alertas, página pública, binder virtual con drag & drop.

---

## 2. Decisiones tomadas

Cada una cierra una pregunta que el PRD dejaba abierta.

| # | Decisión | Motivo |
|---|---|---|
| D1 | **Moneda única: USD.** `Purchase` no tiene campo de moneda ni tabla de tipo de cambio. | Las compras en soles se ingresan ya convertidas; el monto en PEN puede anotarse en `notas`. Elimina toda la aritmética de FX. |
| D2 | **Sin flete ni envíos.** `Purchase` tiene un solo `total_usd`. | No se modela el casillero de Miami ni el flete consolidado. El precio que ingresas es el costo total de esa compra. |
| D3 | **Meta del 151 por especie.** Cualquier carta de un Pokémon llena su casillero. | Coincide con cómo ya trabajas: la hoja *Guía* del Excel dice "escribe una x cuando consigas al Pokémon (con cualquiera de sus opciones)". |
| D4 | **Identificación asíncrona.** Guardar nunca espera al reconocimiento. | Es la única forma de garantizar los 30 segundos con señal mala en tienda. |
| D5 | **Precio congelado al cachear.** Se guarda `tcgplayer.marketPrice` en el momento de traer la ficha. Sin job de refresco. | TCGdex devuelve el precio dentro de la misma respuesta del catálogo (verificado, ver [§3](#3-hallazgos-verificados-sobre-tcgdex)). Aprovecharlo es casi gratis; refrescarlo semanalmente es fase 2. |
| D6 | **Sin API de precios aparte.** JustTCG y PriceCharting quedan fuera. | Solo harían falta para variantes vintage (shadowless, 1st Ed), que tu propia Guía te recomienda no comprar. |
| D7 | **Espejo perezoso del catálogo, no self-hosting.** | El dataset open source de TCGdex no trae precios (verificado). Como igual se congela el precio al cachear, el cache *es* el espejo. Cero infraestructura extra. |
| D8 | **Wishlist editable de primera clase.** Las 4 opciones × 151 se importan como `wishlist_item`; puedes agregar y quitar libremente. | El Excel es una semilla, no una estructura fija. |
| D9 | **Auto-resolución con heurística** para las opciones ambiguas del Excel, marcadas para corrección. | Import instantáneo sin trabajo manual previo, con la corrección disponible cuando la necesites. |
| D10 | **Ubicación física: binder → página.** Sin bolsillo. | No hay binder físico todavía; el bolsillo se agrega cuando exista uno. |
| D11 | **Stack: FastAPI + Next.js + Postgres + GCS.** | Decisión del dueño. |
| D12 | **Captura tipo "foto primero, enriquecer después"** (enfoque C). | Ver [§6](#6-flujo-de-captura). |

---

## 3. Hallazgos verificados sobre TCGdex

Consultado el 2026-08-15 contra `api.tcgdex.net/v2/en`.

**El catálogo trae precios.** `GET /cards/sv03.5-199` (Charizard ex, set 151) devuelve un objeto `pricing` con TCGplayer en USD (`marketPrice`, `lowPrice`, `midPrice`, `highPrice`, `directLowPrice`) y Cardmarket en EUR (`avg`, `low`, `trend`, `avg1`, `avg7`, `avg30`), con timestamp de actualización del mismo día.

**El precio es por variante, no por carta.** `GET /cards/base1-4` (Charizard Base Set) devuelve `variants_detailed` con cuatro entradas:

| `type` | `subtype` | `stamp` | pricing |
|---|---|---|---|
| holo | unlimited | — | completo |
| holo | shadowless | `["1st-edition"]` | `null` |
| holo | shadowless | — | `null` |
| holo | 1999-2000-copyright | — | ausente |

Cada entrada tiene un `variantId` propio. Consecuencia: el modelo de datos guarda el precio en la variante, y las variantes vintage caras no tienen precio disponible.

**El dataset open source no trae precios.** Los archivos de `tcgdex/cards-database` (por ejemplo `data/Base/Base Set/4.ts`) contienen nombre, ilustrador, rareza, ataques y habilidades — ningún campo de precio. El pricing lo agrega el servicio hosteado. Esto invalida el argumento del PRD §6.1 de que self-hostear da control total: el precio seguiría viniendo de fuera.

---

## 4. Arquitectura

**Frontend:** Next.js (App Router) como PWA instalable, móvil-first. Service worker con cola de reintentos en IndexedDB.
**Backend:** FastAPI + Postgres. Un proceso web y un proceso worker.
**Almacenamiento de fotos:** GCS con subida directa desde el navegador vía URL firmada. Thumbnails generados por el worker.
**Autenticación:** usuario único, mínima.

### 4.1 Puertos

Tres dependencias externas, cada una detrás de una interfaz con un adaptador real y un fake para tests:

- **`CatalogPort`** — TCGdex. `get_card(id)`, `find_by_set_and_number(set, number)`, `search(query)`.
- **`RecognitionPort`** — visión LLM. `identify(image_url) -> {name, set, number, confidence, needs_review}`.
- **`GeocodingPort`** — Google Places. `nearby(lat, lng) -> [Place]`.

### 4.2 Worker

La cola de trabajo asíncrono vive en Postgres, en la tabla `job`, consultada en loop por el proceso worker. Cubre dos tipos de trabajo: identificar la carta y generar thumbnails. No se usa Redis ni Celery: `BackgroundTasks` de FastAPI pierde trabajos al reiniciar, y Redis es infraestructura extra para un volumen de unos pocos jobs al día. Una tabla da reintentos, historial e inspección con un `SELECT`.

### 4.3 Módulos

| Módulo | Responsabilidad | Depende de |
|---|---|---|
| `catalog` | Espejo perezoso, resolución de variantes, congelado de precios | `CatalogPort` |
| `capture` | Borradores, URLs firmadas, PATCHes idempotentes | `catalog` |
| `recognition` | Cola de jobs, validación del output, cola de revisión | `RecognitionPort`, `catalog` |
| `collection` | Ejemplares, binder, ubicación, búsqueda | `catalog` |
| `purchases` | Compras y prorrateo | `collection`, `catalog` |
| `wishlist` | Checklist 151, wishlist, import del Excel | `catalog` |
| `dashboard` | Agregaciones de progreso e inversión | lectura de todos |

Cada módulo posee sus tablas y expone funciones; ningún módulo lee tablas de otro directamente.

---

## 5. Modelo de datos

### `card` — espejo del catálogo

| Campo | Tipo | Nota |
|---|---|---|
| `id` | text PK | ID de TCGdex, ej. `sv03.5-199` |
| `name` | text | |
| `set_id`, `set_name` | text | |
| `local_id` | text | Número dentro del set, ej. `199` |
| `set_card_count` | int | Para reconstruir `199/165` |
| `rarity` | text | |
| `image_url` | text | |
| `dex_number` | int null | Primer elemento de `dexId` |
| `raw` | jsonb | Payload completo |
| `cached_at` | timestamptz | |

### `card_variant` — una fila por entrada de `variants_detailed`

| Campo | Tipo | Nota |
|---|---|---|
| `id` | text PK | `variantId` de TCGdex |
| `card_id` | text FK | |
| `type` | text | `holo`, `normal`, `reverse`, `firstEdition`, `wPromo` |
| `subtype` | text null | `unlimited`, `shadowless`, `1999-2000-copyright` |
| `stamp` | text[] | ej. `{1st-edition}` |
| `price_usd` | numeric null | `tcgplayer.marketPrice` congelado |
| `price_captured_at` | timestamptz null | |
| `raw` | jsonb | |

### `owned_copy` — el ejemplar físico

Dos ejes de estado **separados**, que el PRD mezclaba en uno solo:

- `capture_status`: `borrador` → `identificando` → `en_revision` → `listo`
- `lifecycle_status`: `en_transito` | `en_binder` | `vendida`

Son ortogonales: una carta puede estar guardada en el binder y aún tener la identificación en revisión.

| Campo | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | |
| `client_draft_id` | uuid unique | Generado en el celular; llave de idempotencia |
| `card_id` | text FK null | Null mientras es borrador |
| `card_variant_id` | text FK null | Null si el chip no mapea a variante conocida |
| `variant_label` | enum | `normal`, `reverse`, `holo`, `first_edition`, `shadowless`, `unlimited` |
| `condition` | enum null | `NM`, `LP`, `MP`, `HP`, `DMG` |
| `graded` | bool | |
| `grading_company`, `grade` | text null, numeric null | |
| `photo_front_url`, `photo_back_url` | text null | |
| `purchase_id` | uuid FK null | |
| `assigned_cost_usd` | numeric null | Resultado del prorrateo |
| `is_bulk` | bool | Excluida del reparto, costo $0 |
| `binder_id` | uuid FK null | |
| `page` | int null | |
| `capture_status`, `lifecycle_status` | enum | |
| `identification_corrected` | bool | Alimenta la métrica de precisión |
| `notes` | text | |
| `created_at`, `updated_at` | timestamptz | |

### `purchase`

`id`, `date`, `source_type` (`tienda_fisica` \| `ebay` \| `tcgplayer` \| `intercambio` \| `regalo` \| `sobre`), `seller`, `listing_url`, `total_usd`, `allocation_method` (`market_value` \| `manual` \| `equal`), `place_id` FK null, `photo_urls` text[], `notes`.

`total_usd` es inmutable respecto al prorrateo: cambiar de método recalcula `assigned_cost_usd` de los ejemplares, nunca el total.

### `place`

`id`, `name`, `city`, `lat`, `lng`, `label`, `is_frequent`.

### `binder`

`id`, `name`, `description`, `cards_per_page` (default 9).

### `wishlist_item`

| Campo | Tipo | Nota |
|---|---|---|
| `id` | uuid PK | |
| `dex_number` | int null | Casillero del 151; null si es un deseo fuera del checklist |
| `card_id` | text FK null | Null cuando la heurística no resolvió |
| `raw_text` | text | String original del Excel |
| `source_option` | enum | `opcion_1`..`opcion_4`, `galeria`, `manual` |
| `auto_resolved` | bool | Resuelto por heurística, pendiente de tu confirmación |
| `is_favorite` | bool | Marca de la Galería de 41 |
| `status` | enum | `deseada`, `cazando`, `comprada_en_transito` |
| `target_price_usd` | numeric null | |
| `reference_value_usd` | numeric null | El USD escrito a mano en el Excel |
| `priority` | int null | |

Dos índices únicos parciales para que el reimport sea idempotente:

```sql
CREATE UNIQUE INDEX ON wishlist_item (dex_number, card_id) WHERE card_id IS NOT NULL;
CREATE UNIQUE INDEX ON wishlist_item (dex_number, raw_text) WHERE card_id IS NULL;
```

### `pokemon`

`dex_number` PK, `name`. Los 151, sembrados del Excel. Necesaria para dibujar los casilleros vacíos de la grilla del dex.

### `mini_project` y `mini_project_member`

`mini_project(id, name)` y `mini_project_member(mini_project_id, dex_number)`. Starters, línea Gengar, aves legendarias. Se siembran a mano.

### `job`

Cola única del worker. `id`, `kind` (`identify` \| `thumbnail`), `owned_copy_id` FK, `status` (`pendiente` \| `corriendo` \| `ok` \| `fallo`), `attempts`, `provider` text null, `raw_response` jsonb null, `confidence` numeric null, `created_at`, `finished_at`.

Los dos tipos de trabajo asíncrono — identificar la carta y generar el thumbnail de la foto — comparten tabla y proceso. Ambos se encolan al confirmarse la subida a GCS.

### Lo que no existe

No hay tabla de progreso del 151. Con la meta por especie es un `count(distinct card.dex_number)` sobre los ejemplares, y `pokemon` provee los casilleros faltantes.

---

## 6. Flujo de captura

Enfoque "foto primero, enriquecer después": el reconocimiento arranca mientras el usuario todavía está tecleando, que es donde se ganan los 30 segundos.

1. Tap en la cámara. El cliente genera `client_draft_id` (UUIDv4) y **guarda el blob en IndexedDB antes de tocar la red**.
2. `POST /captures` con el `client_draft_id` → devuelve URL firmada de GCS.
3. La foto sube **directo a GCS**, sin pasar por FastAPI. Un multipart desde móvil a través del backend es el cuello de botella clásico de este flujo.
4. `POST /captures/{client_draft_id}/photo-uploaded` → crea el `owned_copy` en `capture_status = borrador` y encola los jobs de identificación y thumbnail. El worker empieza a trabajar.
5. En paralelo, en el celular: chips de variante → PATCH; precio y compra → PATCH; ubicación → PATCH.
6. Guardar. Si la identificación ya volvió, la pantalla muestra la carta reconocida para que confirmes. Si no, el ejemplar queda en `identificando` y se resuelve solo.

La ubicación en binder puede asignarse después, en lote, desde desktop.

### 6.1 Validación del reconocimiento

El worker acepta el output del LLM **solo si el número de colección y el set hacen match exacto** contra el catálogo vía `CatalogPort.find_by_set_and_number()`. Cualquier otro caso — confianza baja, `needs_review`, número que no existe, set ambiguo — va a `capture_status = en_revision`. Nunca se guardan datos dudosos como si fueran ciertos.

### 6.2 Mapeo de chip a variante

El chip da un `variant_label`. Con `card_id` + `variant_label` se busca la fila de `card_variant` correspondiente:

Los chips se muestran en dos grupos que **no se solapan**, según el set de la carta reconocida: los tres modernos siempre, los tres vintage solo para sets WOTC (1999-2003).

| Grupo | Chip | Criterio de búsqueda |
|---|---|---|
| Moderno | Normal | `type = normal` |
| Moderno | Reverse | `type = reverse` |
| Moderno | Holo | `type = holo` y `subtype` nulo |
| Vintage | 1st Edition | `stamp` contiene `1st-edition` |
| Vintage | Shadowless | `subtype = shadowless` y `stamp` vacío |
| Vintage | Unlimited | `subtype = unlimited` |

Mientras la carta no está identificada (captura asíncrona) se muestran ambos grupos; al resolverse, el grupo que no corresponde se oculta y, si el chip elegido quedó fuera, el ejemplar pasa a `en_revision`.

Si hay cero o múltiples coincidencias, `card_variant_id` queda null y el ejemplar no tiene precio de mercado. Es un estado válido, no un error.

### 6.3 Offline

Todos los pasos posteriores al 2 son PATCHes idempotentes contra `client_draft_id`. El service worker los reintenta con backoff. El endpoint de creación hace upsert, así que reenviar no duplica. Sin señal, la foto y el borrador viven en IndexedDB y todo se procesa al reconectar.

**Limitación conocida:** Background Sync no existe en Safari/iOS, así que en iPhone la sincronización solo ocurre con la PWA abierta. Aceptable: el caso típico es registrar y volver a tener señal en minutos.

---

## 7. Prorrateo de compras

Una `Purchase` agrupa N ejemplares y reparte `total_usd` entre ellos.

**`market_value` (default).** Peso de cada ejemplar = `card_variant.price_usd`. Si algún ejemplar no tiene precio, la UI lo señala y ofrece dos salidas: cambiar a manual, o marcar ese ejemplar como bulk.

**`manual`.** El usuario escribe el costo de cada carta; la UI muestra el residuo contra el total en vivo y no deja guardar si no cuadra.

**`equal`.** `total_usd / n`.

**Bulk.** Los ejemplares con `is_bulk = true` reciben `assigned_cost_usd = 0` y quedan fuera del reparto; las demás absorben todo. Refleja "compré el lote por una carta".

**Redondeo.** Todo a centavos. El residuo del redondeo se asigna al ejemplar de mayor valor, de modo que la suma de `assigned_cost_usd` sea exactamente igual a `total_usd` siempre.

**Recálculo.** Cambiar `allocation_method` recalcula los costos asignados. `total_usd` nunca se modifica.

**Sobres.** Un sobre es una `Purchase` con `source_type = sobre` cuyo costo se prorratea entre los pulls, lo que habilita la métrica "valor abierto vs. gastado en sobres".

---

## 8. Geolocalización

Solo para `source_type = tienda_fisica`. Tap en "usar mi ubicación" → permiso del navegador → lat/lng → `GeocodingPort.nearby()` → chips con los comercios cercanos → un tap guarda el `Place`. Los lugares frecuentes se ofrecen primero, sin necesidad de GPS.

Fallback si registras después: extracción de GPS del EXIF de la foto.

**Privacidad:** la ubicación se captura únicamente al accionar el botón, nunca en background, y no sale de tu instancia.

---

## 9. Import del Excel

Fuente: `Pokedex_Viviente_151.xlsx`, tres hojas (*Pokédex 151*, *Guía*, *Galería favoritos*).

**Hoja Pokédex 151.** 151 filas, cada una con hasta cuatro opciones de adquisición:

- **Opciones 1 y 2** traen número de colección (`Bulbasaur 001/165`, `Bulbasaur 166/165`) → match determinístico contra el set `sv03.5`.
- **Opciones 3 y 4** son texto libre (`Venusaur Base Set Holo`, `Ivysaur Southern Islands`) → heurística: búsqueda por nombre + set, se prefiere `subtype = unlimited` y se descartan `shadowless` y `1st-edition`, siguiendo la recomendación de la propia hoja *Guía*. Se marcan `auto_resolved = true`.
- Los USD escritos a mano van a `reference_value_usd`.
- Lo que no resuelve queda con `card_id` null y su `raw_text`, utilizable para copiar y pegar en el buscador como haces hoy.

**Hoja Galería favoritos.** 41 filas. Si la carta ya existe como wishlist item (varias filas dicen literalmente "Ya está en tu Opción 2"), se le marca `is_favorite = true` en lugar de crear un duplicado. Si no existe, se crea con `source_option = galeria`.

**El import no crea ejemplares.** La columna ✔ se ignora por completo — la única marcada es la fila de ejemplo de Bulbasaur que la hoja *Guía* indica borrar. Los `owned_copy` nacen exclusivamente del flujo de captura con foto, que es lo que sostiene la garantía de "cero cartas perdidas".

**Reimport.** Idempotente gracias a los índices únicos parciales. Las correcciones manuales sobre items `auto_resolved` no se pisan: el reimport no modifica un item cuyo `auto_resolved` ya fue puesto en `false`.

---

## 10. Manejo de errores

El principio: **ninguna falla puede costarte la foto**. Es lo único irrecuperable una vez que saliste de la tienda.

| Falla | Comportamiento |
|---|---|
| GCS no responde | El blob sigue en IndexedDB; el service worker reintenta con backoff |
| TCGdex caído | El espejo sirve lo cacheado; las cartas nuevas no resuelven y el ejemplar queda `en_revision` con la foto a salvo |
| Reconocimiento falla o duda | `en_revision`. Nunca datos dudosos guardados como ciertos |
| Worker agota reintentos (3, con backoff) | `en_revision` y el job queda en `fallo` con la respuesta cruda para inspección |
| Variante sin precio | `card_variant_id` o `price_usd` null; el prorrateo por valor se deshabilita con aviso y se ofrece `reference_value_usd` |
| Permiso de ubicación denegado | Fallback a lugares frecuentes y a EXIF |
| PATCH duplicado | Upsert por `client_draft_id`; sin efecto |

---

## 11. Dashboard y métricas

**Dashboard del MVP:** progreso del 151 en grilla de dex (`count(distinct dex_number)` sobre ejemplares, con los casilleros vacíos de `pokemon`), progreso por mini-proyecto, total invertido (suma de `assigned_cost_usd`), valor de mercado (suma de `price_usd` congelados, etiquetado como "valor al día que registraste"), P&L absoluto y porcentual, costo promedio por carta, y gasto mensual contra el presupuesto.

Toda cifra de valor de mercado se muestra con la fecha del precio congelado. No es un valor en vivo y la UI no debe sugerir que lo sea.

**Métricas de éxito:**

| Métrica | Objetivo |
|---|---|
| Tiempo mediano de registro | < 30 s |
| Tasa de corrección de identificaciones | < 15% (`identification_corrected` / identificadas automáticamente) |
| Cartas perdidas | 0 — toda carta del binder existe en la app con ubicación |
| Uso sostenido | Registro dentro de las 24 h de cada adquisición, 8 semanas seguidas |

La segunda reemplaza al ">85% de identificación correcta al primer intento" del PRD §9, que no era medible: la cola de revisión solo contiene los rechazos de baja confianza, así que las identificaciones aceptadas-pero-equivocadas eran invisibles; y con identificación asíncrona ya no existe un "primer intento" que el usuario presencie. El contador de correcciones sí es observable.

---

## 12. Requisitos no funcionales

**Export.** Un endpoint que vuelca toda la base a CSV (un archivo por tabla, en un zip) y a un Excel de una hoja por entidad. Disponible en cualquier momento, sin ceremonia: la data es tuya, no de la app. Este requisito es el que hace que la app no sea una jaula, así que entra al MVP y no a fase 2.

**Backup.** Dump diario de Postgres a GCS con retención de 30 días. Las fotos ya viven en GCS con versionado del bucket.

**PWA.** Instalable, con manifest e íconos. El service worker cachea el shell de la app y la grilla del dex para que el checklist se pueda consultar sin señal — el caso "estoy en la tienda decidiendo si ya tengo este Pokémon" no puede depender de la red.

**Rendimiento.** El presupuesto de los 30 segundos se mide desde el tap de la cámara hasta el guardado, en 4G y con la PWA ya abierta. La subida de la foto no bloquea la interacción.

---

## 13. Cambios respecto al PRD

| PRD | Cambio |
|---|---|
| §4 `Purchase` con `costo de envío` | Eliminado. Un solo `total_usd` (D2) |
| §4 `OwnedCopy.variante` como enum plano | Se guardan `variant_label` (enum) **y** `card_variant_id` (TCGdex), porque el precio es por variante |
| §4 estado único de `OwnedCopy` | Separado en `capture_status` y `lifecycle_status` |
| §4 `PriceSnapshot` (fase 2) | Sin cambios; sigue en fase 2 |
| §5.5 binder → página → bolsillo | Solo binder → página (D10) |
| §6.1 TCGdex self-hosted | Espejo perezoso sobre la API pública (D7) |
| §6.3 API de precios como parte del MVP | Eliminada. TCGdex ya trae precios (D5, D6) |
| §9 ">85% de identificación al primer intento" | Reemplazada por tasa de corrección (§11) |
| §5.2 identificación dentro del flujo | Asíncrona, con subida de foto temprana (D4, D12) |

---

## 14. Estrategia de tests

TDD, con fakes para los tres puertos. La prioridad no es cobertura sino los tres lugares donde un bug es caro y silencioso:

1. **Prorrateo** — los tres métodos, bulk $0, redondeo con residuo, recálculo tras cambio de método. Es aritmética pura y un centavo descuadrado envenena el P&L completo.
2. **Idempotencia** — el mismo `client_draft_id` dos veces produce un solo ejemplar; reimportar el Excel dos veces no duplica wishlist ni pisa correcciones manuales.
3. **Contrato con TCGdex** — un test que falla si el payload deja de traer `pricing` o `variants_detailed`. Todo el modelo de precios descansa en esa forma y es una dependencia externa que puede cambiar sin avisar.

También: validación del reconocimiento (que un número inexistente vaya a `en_revision`), heurística del import contra casos reales del Excel, y un E2E del flujo de captura.

El piloto de 30 fotos reales (tienda, casa, con sleeve) es criterio de aceptación manual del reconocimiento, no un test automatizado.

---

## 15. Riesgos abiertos

| Riesgo | Mitigación |
|---|---|
| Precisión de la visión LLM con reflejos de holos y sleeves | Validación por número de colección + cola de revisión. `RecognitionPort` permite cambiar a CardVault sin tocar el resto |
| Precio congelado envejece y el P&L deja de ser real | Etiquetado explícito con fecha en toda la UI. El refresco es fase 2 y el modelo ya lo soporta (basta reescribir `price_usd` y `price_captured_at`) |
| Sin Background Sync en iOS | Aceptado. La cola sincroniza con la PWA abierta |
| La heurística del import vincula cartas equivocadas en silencio | `auto_resolved = true` las marca todas; la UI las lista para revisión en bloque |
| Cobertura de TCGdex en vintage | Verificable temprano: el import del Excel resuelve las Opciones 3 y 4 y reporta cuántas quedaron sin `card_id` |
