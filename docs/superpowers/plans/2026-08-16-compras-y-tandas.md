# Compras: sobres, lotes y fotos por tanda — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Registrar un sobre o un lote entero: varias fotos, varias cartas en cada una, un solo precio, y el costo repartido entre ellas.

**Architecture:** La compra pasa a ser el contenedor. Hoy la unidad de captura es la carta y eso hace imposible un sobre de diez. Se añade `app.purchase`, cada ejemplar cuelga de una, y el costo se reparte al final con un método recalculable. La foto deja de ser obligatoriamente por carta: una foto puede traer varias.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md` §5.3

## Lo que midió la decisión

Probado contra Gemini con fotos compuestas a resolución de celular:

| Cartas en una foto | Tamaño de cada una | Aciertos | Latencia |
|---|---|---|---|
| 4 | 420×586 px | 4/4 | 9.5 s |
| 12 | 509×712 px | **12/12** | 17.5 s |
| 24 | 382×534 px | 23/24 | 16.5 s |

**Doce es el máximo medido sin error.** A 24 leyó el `047` como `022`, con confianza 0.98 y sin marcar duda alguna. En ese set, `047` es *Mega Froslass ex* y `022` es *Mega Charizard Y ex*: distinto Pokémon, distinto precio, y **el número equivocado existe**, así que pasa todas las validaciones del catálogo.

Ese fallo silencioso gobierna tres decisiones de este plan: el límite por tanda, que la confirmación muestre **el arte** y no el número, y que la app pregunte cuántas cartas había.

## Global Constraints

- **Las tablas viven en el esquema `app`**, RLS habilitada.
- **Moneda única USD**, `Decimal` en Python, `float` solo en el borde HTTP.
- **El total pagado es inmutable.** Cambiar el método de reparto recalcula lo asignado; nunca toca el total.
- **Ningún test de la suite por defecto pega a la red.**
- **Cada llamada real cuesta dinero del dueño.** Una llamada por tanda, sin reintentos automáticos.
- **La variante sigue siendo del humano.** El modelo no la propone.
- **Copy en español**, sentence case, sin voseo.

---

## Task 1: La compra existe y todo ejemplar cuelga de una

Unificar el costo en un solo sitio. Hoy `owned_copy.purchase_price_usd` es un número suelto; con compras habría dos fuentes de verdad para "cuánto costó esta carta", y tarde o temprano un informe suma la columna equivocada.

**Files:**
- Create: `supabase/migrations/<ts>_create_purchase.sql`
- Modify: `backend/src/pokedex/collection/models.py`, `repository.py`
- Test: `backend/tests/collection/test_schema.py`, `test_repository.py`

- [ ] **Step 1: El DDL**

```sql
create table app.purchase (
  id                bigint generated always as identity primary key,
  fecha             date not null default current_date,
  source_type       text not null,
  total_usd         numeric(12, 2) not null,
  allocation_method text not null default 'market_value',
  photo_url         text,
  notes             text,
  created_at        timestamptz not null default now(),
  constraint purchase_source_valida check (
    source_type in ('sobre', 'lote', 'tienda', 'online', 'intercambio', 'regalo')
  ),
  constraint purchase_metodo_valido check (
    allocation_method in ('market_value', 'manual', 'equal')
  ),
  constraint purchase_total_no_negativo check (total_usd >= 0)
);

alter table app.owned_copy
  add column purchase_id bigint references app.purchase (id) on delete set null,
  add column assigned_cost_usd numeric(12, 2),
  add column is_bulk boolean not null default false;

create index owned_copy_purchase_idx on app.owned_copy (purchase_id);
alter table app.purchase enable row level security;
```

`on delete set null` y no `cascade`: borrar una compra registrada por error no puede llevarse por delante las cartas, que existen físicamente.

- [ ] **Step 2: Migrar el precio suelto**

`purchase_price_usd` se conserva por ahora, pero **el costo de un ejemplar pasa a leerse como `coalesce(assigned_cost_usd, purchase_price_usd)`** en un único sitio, una función o una vista, para que nadie vuelva a elegir columna a mano. Documentar en el código que la segunda es el respaldo histórico y que desaparecerá cuando todo tenga compra.

- [ ] **Step 3: Tests**

Existencia y RLS; el total no admite negativos; un método inválido se rechaza; borrar una compra deja las cartas vivas con `purchase_id` nulo; un ejemplar sin compra sigue devolviendo su precio suelto.

---

## Task 2: El reparto del costo

**Files:**
- Create: `backend/src/pokedex/purchases/__init__.py`, `allocation.py`
- Test: `backend/tests/purchases/test_allocation.py`

Función pura, sin base ni red: recibe el total y la lista de ejemplares con su precio de mercado, devuelve cuánto le toca a cada uno.

- [ ] **Step 1: Los tres métodos**

- **`market_value`** — cada carta absorbe en proporción a su precio de mercado. Es el que refleja la realidad de un lote heterogéneo.
- **`equal`** — total entre número de cartas.
- **`manual`** — el dueño escribe cada costo; la función solo valida que la suma cuadre y devuelve el residuo en vivo.

- [ ] **Step 2: Bulk a cero**

Los ejemplares con `is_bulk` reciben cero y **quedan fuera del reparto**: las demás absorben el total. Es lo que hace honesto un "compré el lote por una carta".

- [ ] **Step 3: Los casos que hay que clavar**

| Caso | Qué debe pasar |
|---|---|
| Todas con precio de mercado | reparto proporcional, suma exacta al total |
| Alguna sin precio en `market_value` | no se puede repartir por valor: error explícito que ofrezca otro método |
| **Todas sin precio** | igual, error explícito y no un reparto en partes iguales encubierto |
| Todas marcadas bulk | error: nadie absorbe el costo |
| Una sola carta | se lleva el total |
| Redondeo a centavos | el residuo va a la carta de mayor valor; **la suma es exactamente el total** |
| Total cero (un regalo) | todas a cero, sin dividir por cero |
| `manual` que no cuadra | error con el residuo, sin guardar nada |

El del redondeo es el que más duele si falla: un centavo perdido por carta en un lote de 50 son 50 centavos que no cuadran, y el P&L deja de sumar.

- [ ] **Step 4: Recalcular no toca el total**

Test explícito: repartir por valor, luego por partes iguales, y comprobar que `total_usd` es idéntico y que la suma de lo asignado sigue cuadrando.

---

## Task 3: Identificar varias cartas en una foto

**Files:**
- Modify: `backend/src/pokedex/recognition/ports.py`, `gemini.py`, `models.py`
- Modify: `backend/src/pokedex/recognition/resolver.py`
- Test: `backend/tests/recognition/test_tanda.py`, `test_tanda_contract.py`

- [ ] **Step 1: El puerto**

`RecognitionPort.identificar_varias(foto: bytes, mime: str) -> list[Recognition]`. Devuelve una lectura por carta visible, en orden de lectura.

El prompt le dice que **no invente cartas que no vea** y que ponga el número en `null` si no lo lee con certeza. Ya se comprobó que devuelve el código de set como `ASCen` — código más idioma — así que el parser **debe separar el sufijo de idioma** antes de buscar la abreviatura.

- [ ] **Step 2: Cada lectura se resuelve por separado**

Cada `Recognition` pasa por el `CardResolver` que ya existe, con sus mismas reglas: código de set, denominador, nombre, y confirmación contra el catálogo. Nada nuevo que validar; se reutiliza entero.

- [ ] **Step 3: El límite y la cuenta**

- **Doce cartas por tanda como máximo recomendado.** Si el modelo devuelve más de doce, se aceptan pero la respuesta lo marca: por encima de ese número la lectura empieza a fallar en silencio y el humano debe revisar con más cuidado.
- La respuesta incluye **cuántas encontró**, para que la pantalla pueda contrastarlo con lo que el dueño dice que hay.

- [ ] **Step 4: Test de contrato**

Uno solo, marcado `contract`: una imagen compuesta con cuatro cartas conocidas, y comprobar que devuelve las cuatro con sus números. No usar 24: el objetivo es verificar el mecanismo, no volver a medir el techo.

---

## Task 4: El endpoint de la compra

**Files:**
- Create: `backend/src/pokedex/purchases/repository.py`, `service.py`
- Create: `backend/src/pokedex/api/routes/purchases.py`
- Modify: `backend/src/pokedex/api/main.py`
- Test: `backend/tests/api/test_purchase_routes.py`

- [ ] **Step 1: Los endpoints**

- `POST /compras` — crea la compra con su tipo y su total, devuelve su id
- `POST /compras/{id}/tanda` — recibe una foto, la identifica y devuelve las lecturas resueltas **sin guardar nada**
- `POST /compras/{id}/ejemplares` — guarda la lista que el dueño confirmó
- `POST /compras/{id}/relleno` — añade N ejemplares bulk sin carta ni foto
- `POST /compras/{id}/repartir` — aplica el método y devuelve lo asignado
- `GET /compras/{id}`

- [ ] **Step 2: Nada se guarda sin confirmar**

`tanda` propone; `ejemplares` guarda. Igual que la identificación de una sola carta: el modelo propone y el humano dispone. Una lectura nunca crea un ejemplar por su cuenta.

- [ ] **Step 3: La foto de la tanda vive en la compra**

Una foto de doce cartas no es la foto de ninguna de ellas. Se guarda en `purchase.photo_url` como evidencia del lote; los ejemplares que salen de una tanda quedan sin foto propia. Ponerla en las doce sería mentir sobre qué muestra cada una.

- [ ] **Step 4: Tests**

Con un `RecognitionPort` falso: una tanda de tres propone tres y no guarda nada; confirmar dos guarda dos; el relleno crea N bulk sin carta; repartir cuadra con el total; repartir dos veces con métodos distintos no cambia el total.

---

## Task 5: La pantalla de la compra

**Files:**
- Create: `frontend/app/compras/nueva/page.tsx` y sus componentes
- Modify: `frontend/app/lib/api.ts`, `types.ts`
- Modify: `frontend/app/binder/Rail.tsx`

- [ ] **Step 1: El flujo, en una pantalla**

1. Qué compraste y cuánto pagaste, **una sola vez**.
2. **"Fotografiar una tanda"**: extiendes las cartas y disparas. Antes de disparar, un campo opcional: *"¿cuántas cartas hay?"*.
3. Vuelve una **lista con el arte de cada carta propuesta**, no con números. Cada fila: la imagen del catálogo, el nombre, el set, el número, y un chip de variante que eliges tú.
4. Puedes quitar filas, corregir una carta, y añadir una a mano.
5. **Otra tanda** para las que falten.
6. **Relleno**: un número, sin fotos, a $0.
7. Eliges el reparto y guardas.

- [ ] **Step 2: El arte es lo que atrapa el error**

La lista muestra la imagen del catálogo de cada carta propuesta, grande. Es la única defensa práctica contra la confusión medida: si te propone un Charizard donde tienes un Froslass, se ve. Un número de tres dígitos en una lista no lo revisa nadie.

- [ ] **Step 3: La cuenta se contrasta en voz alta**

Si dijiste que había doce y encontró once, la pantalla lo dice antes de dejarte seguir: *"Encontré 11 de las 12 que dijiste. Toma otra foto o añade la que falta a mano."* Si no dijiste cuántas, dice cuántas encontró y pregunta si están todas.

- [ ] **Step 4: El aviso de tanda grande**

Con más de doce cartas en una foto, un aviso antes de confirmar: por encima de ese número la lectura empieza a fallar sin avisar, y conviene revisar el arte una a una o partir en dos fotos.

- [ ] **Step 5: Verificar de punta a punta en la IP de red**

Registrar un lote real de varias cartas con dos tandas, repartir por valor de mercado, y comprobar que la suma de lo asignado es exactamente el total. Borrar lo de prueba al terminar.

---

## Verificación del plan completo

- [ ] Un sobre de diez se registra con una foto y un precio
- [ ] Un lote con dos tandas y relleno reparte el costo y la suma cuadra al centavo
- [ ] Cambiar el método de reparto no altera el total pagado
- [ ] La lista de confirmación muestra el arte de cada carta propuesta
- [ ] Si encuentra menos de las que dijiste, lo dice antes de dejarte seguir
- [ ] Una carta marcada bulk cuesta cero y las demás absorben el total
- [ ] La suite pasa sin red

## Qué queda fuera

- El envío y el casillero de Miami: sigue fuera por decisión del dueño; una compra tiene un solo total.
- Añadir una foto propia a un ejemplar salido de una tanda: necesita una pantalla de edición que no existe.
- Vender y P&L realizado: fase posterior del spec.
