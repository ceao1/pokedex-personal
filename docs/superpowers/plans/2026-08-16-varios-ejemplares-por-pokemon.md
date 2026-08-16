# Varios ejemplares por Pokémon — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Coleccionar varias versiones del mismo Pokémon —tres Charmander distintos, dos Bulbasaur— todas colgando de su casillero de los 151, y poder verlas.

**Architecture:** Sin cambios de modelo. `app.owned_copy` no tiene restricción de unicidad por carta y cada ejemplar cuelga de su casillero a través de `card.dex_number`, así que el dato ya se puede guardar. Lo que falta es exponerlo y dibujarlo.

**Tech Stack:** El mismo.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`

## Lo que pidió el dueño, literal

> "deja los ciento cincuenta y un pokemones normales, o sea, no pongas secciones especiales, pero lo que yo sí quiero hacer es poder coleccionar varios del mismo. Por ejemplo, varios bulbas o varios charmander, que puedan quedar linkeados al charmander original, pero yo pueda ver mis distintas versiones. No necesariamente tienes que cargar todas las versiones de una misma carta."

Tres cosas, y la tercera es tan importante como las otras:

1. **La estructura de los 151 no se toca.** Nada de una sección aparte para variantes ni una segunda grilla. Un casillero por Pokémon, diecisiete páginas, como hoy.
2. **Varios ejemplares por casillero**, cada uno con su versión, colgando del Pokémon.
3. **No precargar todas las versiones existentes de una carta.** Solo entran al catálogo las que el dueño realmente tiene o persigue. Eso ya es exactamente lo que hace el espejo perezoso; este plan no lo cambia.

## Global Constraints

- **Las tablas viven en el esquema `app`**, RLS habilitada.
- **Moneda única USD**, `Decimal` en Python, `float` solo en el borde HTTP.
- **Ningún test de la suite por defecto puede pegarle a la red.**
- **`owned_count` y nunca `wishlist_count`** decide si algo está conseguido.
- **Copy en español**, sentence case, voz activa.
- **Sin librería de componentes ni Tailwind.** CSS Modules y los ocho tokens de color existentes.
- **La foto del ejemplar es del dueño** y vive en el bucket privado; se sirve con URL firmada.

---

## Decisión de diseño: el bolsillo muestra tu carta, no la que persigues

Hoy el bolsillo dibuja siempre el arte de la ruta más barata, en gris. Eso es correcto mientras no tengas la carta. En cuanto la tienes, mostrar la que persigues es mentira: ya no persigues nada, y la carta que tienes puede ser otra impresión.

A partir de este plan:

- **Sin ejemplares:** el arte de la ruta más barata, en gris. Igual que hoy.
- **Con un ejemplar:** **tu** carta, a color. La que de verdad está en el binder.
- **Con varios:** tu carta a color, con los cantos de las demás asomando detrás como cartas apiladas en la funda, y un contador `×3`.

El apilado no es adorno: es lo que se ve al meter tres cartas en un mismo bolsillo de un binder físico, y es la única señal en la grilla de que ahí hay más de una. El contador lo dice con texto para que no dependa solo de la forma.

Y una regla que evita una mentira nueva: **el progreso del 151 sigue contando Pokémon, no cartas.** Tres Charmander son un casillero lleno, no tres. El contador del riel ya cuenta Pokémon con al menos un ejemplar; este plan no lo toca.

---

## Estructura de archivos

```
backend/src/pokedex/
  collection/repository.py     # MODIFICAR: listar ejemplares por dex
  wishlist/repository.py       # MODIFICAR: la carta preferida es la tuya si la tienes
  api/routes/pokedex.py        # MODIFICAR: /pokedex/{dex} devuelve tus ejemplares
frontend/app/
  lib/types.ts                 # MODIFICAR
  lib/api.ts                   # MODIFICAR
  binder/Pocket.tsx            # MODIFICAR: apilado y contador
  binder/Pocket.module.css     # MODIFICAR
  pokemon/[dex]/page.tsx       # NUEVO: la ficha
  pokemon/[dex]/Ficha.tsx      # NUEVO
  pokemon/[dex]/Ficha.module.css  # NUEVO
```

---

## Task 1: El backend sabe qué ejemplares tienes de cada Pokémon

**Files:**
- Modify: `backend/src/pokedex/collection/repository.py`
- Modify: `backend/src/pokedex/wishlist/repository.py`
- Test: `backend/tests/collection/test_repository.py`
- Test: `backend/tests/wishlist/test_repository.py`

**Interfaces:**
- Produces: `collection.repository.listar_por_dex(conn, dex_number) -> list[dict]`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

En `backend/tests/collection/test_repository.py`:

```python
def _sembrar_pokemon_y_carta(conn, dex, card_id, nombre, local_id):
    conn.execute(
        "insert into app.pokemon (dex_number, name) values (%s, %s) on conflict do nothing",
        (dex, nombre),
    )
    conn.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values (%s, %s, 'sv03.5', '151', %s, %s, %s, '{}'::jsonb)
        on conflict do nothing
        """,
        (card_id, nombre, local_id, dex, f"https://x/{local_id}/high.png"),
    )


def test_listar_por_dex_devuelve_los_ejemplares_de_ese_pokemon(clean_db):
    from uuid import uuid4
    from pokedex.collection import repository

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    _sembrar_pokemon_y_carta(clean_db, 1, "sv03.5-001", "Bulbasaur", "001")
    for card_id in ("sv03.5-004", "sv03.5-004", "sv03.5-001"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, %s)",
            (uuid4(), card_id),
        )

    charmanders = repository.listar_por_dex(clean_db, 4)
    assert len(charmanders) == 2, "dos ejemplares del mismo Pokémon son dos, no uno"
    assert {c["card_id"] for c in charmanders} == {"sv03.5-004"}
    assert len(repository.listar_por_dex(clean_db, 1)) == 1


def test_dos_impresiones_distintas_del_mismo_pokemon_conviven(clean_db):
    """El caso que pidió el dueño: varios Charmander de sets distintos."""
    from uuid import uuid4
    from pokedex.collection import repository

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    _sembrar_pokemon_y_carta(clean_db, 4, "base1-46", "Charmander", "46")
    for card_id in ("sv03.5-004", "base1-46"):
        clean_db.execute(
            "insert into app.owned_copy (client_draft_id, card_id) values (%s, %s)",
            (uuid4(), card_id),
        )

    ejemplares = repository.listar_por_dex(clean_db, 4)
    assert {e["card_id"] for e in ejemplares} == {"sv03.5-004", "base1-46"}
    assert {e["set_name"] for e in ejemplares} == {"151"}


def test_una_carta_vendida_no_aparece_entre_tus_ejemplares(clean_db):
    from uuid import uuid4
    from pokedex.collection import repository

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        """
        insert into app.owned_copy (client_draft_id, card_id, lifecycle_status)
        values (%s, 'sv03.5-004', 'vendida')
        """,
        (uuid4(),),
    )
    assert repository.listar_por_dex(clean_db, 4) == []


def test_los_ejemplares_traen_lo_necesario_para_dibujarlos(clean_db):
    from uuid import uuid4
    from pokedex.collection import repository

    _sembrar_pokemon_y_carta(clean_db, 4, "sv03.5-004", "Charmander", "004")
    clean_db.execute(
        """
        insert into app.owned_copy
          (client_draft_id, card_id, condition, purchase_price_usd, photo_front_url, notes)
        values (%s, 'sv03.5-004', 'NM', 1.50, 'abc/front.jpg', 'de la tienda de Miraflores')
        """,
        (uuid4(),),
    )
    ejemplar = repository.listar_por_dex(clean_db, 4)[0]
    for campo in ("id", "card_id", "card_name", "set_name", "image_url", "condition",
                  "purchase_price_usd", "photo_front_url", "notes", "created_at"):
        assert campo in ejemplar, f"falta {campo}"
```

En `backend/tests/wishlist/test_repository.py`:

```python
def test_el_bolsillo_muestra_tu_carta_cuando_la_tienes(clean_db):
    """Con la carta en la mano ya no persigues nada: el bolsillo enseña la tuya."""
    from uuid import uuid4

    _sembrar_carta(clean_db)
    repository.upsert_wishlist_item(clean_db, _item())
    clean_db.execute(
        """
        insert into app.card (id, name, set_id, set_name, local_id, dex_number, image_url, raw)
        values ('base1-44', 'Bulbasaur', 'base1', 'Base Set', '44', 1,
                'https://x/base/44/high.png', '{}'::jsonb)
        """
    )
    clean_db.execute(
        "insert into app.owned_copy (client_draft_id, card_id) values (%s, 'base1-44')",
        (uuid4(),),
    )
    fila = next(f for f in repository.list_pokedex(clean_db) if f["dex_number"] == 1)
    assert fila["primary_image_url"] == "https://x/base/44/high.png"
    assert fila["owned_count"] == 1
```

- [ ] **Step 2: Escribir `listar_por_dex`**

En `backend/src/pokedex/collection/repository.py`, una consulta que une `owned_copy` con su carta y filtra por el `dex_number` de la carta, excluyendo las vendidas, ordenada por `created_at` descendente. Devuelve además `card_name`, `set_name`, `image_url`, `rarity` y `local_id` de la carta, para que la ficha pueda dibujarse sin una segunda consulta.

- [ ] **Step 3: La carta preferida es la tuya si la tienes**

En `_LIST_POKEDEX`, `primary_image_url` / `primary_card_name` pasan a preferir la carta de un ejemplar propio y solo caen a la ruta más barata cuando no hay ninguno. Debe seguir siendo una subconsulta escalar: un join volvería a multiplicar filas, que es un bug que este repositorio ya tuvo dos veces.

`primary_price_usd` **no** cambia de significado: sigue siendo el costo de la ruta más barata, porque alimenta "Completar el 151", que solo suma los que aún no tienes.

- [ ] **Step 4: Correr, formatear y commitear**

---

## Task 2: `/pokedex/{dex}` devuelve tus ejemplares

**Files:**
- Modify: `backend/src/pokedex/api/routes/pokedex.py`
- Test: `backend/tests/api/test_pokedex_routes.py`

- [ ] **Step 1: Escribir el test**

`GET /pokedex/4` con dos ejemplares devuelve `copies` con dos entradas, cada una con su `photo_url` firmada cuando tiene foto y `null` cuando no.

- [ ] **Step 2: Ampliar el DTO**

`PokemonDetailOut` gana `copies: list[OwnedCopyOut]`. `OwnedCopyOut` lleva `id`, `card_id`, `card_name`, `set_name`, `local_id`, `variant_label`, `condition`, `purchase_price_usd`, `photo_url`, `notes`, `created_at`.

**La foto se sirve firmada.** El bucket es privado: la ruta guardada en `photo_front_url` no es accesible por sí sola. La ruta debe pedirle al `StoragePort` una URL firmada para cada ejemplar que tenga foto. Firma en lote, no una petición por ejemplar dentro de un bucle sin control.

Si firmar falla, el ejemplar se devuelve con `photo_url: null` en vez de reventar la ficha entera: la foto es un adorno de esa pantalla, los datos no.

- [ ] **Step 3: Correr y commitear**

---

## Task 3: El bolsillo apilado

**Files:**
- Modify: `frontend/app/lib/types.ts`
- Modify: `frontend/app/binder/Pocket.tsx`
- Modify: `frontend/app/binder/Pocket.module.css`

- [ ] **Step 1: El apilado**

Cuando `owned_count > 1`, detrás de la carta asoman los cantos de las demás: dos pseudo-elementos desplazados unos píxeles en diagonal, con el color del bolsillo y un borde tenue. Máximo dos cantos aunque haya cinco ejemplares — más se vuelve ruido y el número ya lo dice.

- [ ] **Step 2: El contador**

Un `×N` en la placa inferior, junto al número de dex, en la tipografía de datos. Solo aparece con más de uno.

- [ ] **Step 3: El `aria-label` dice cuántos**

`"Charmander, número 004, tienes 3 ejemplares"` frente a `"…, tienes 1 ejemplar"` y `"…, todavía no lo tienes"`. El apilado es una señal visual; el texto es la que funciona para todos.

- [ ] **Step 4: El bolsillo enlaza a la ficha**

Hoy enlaza a `/registrar`. Pasa a enlazar a `/pokemon/{dex}`, que es de donde se puede registrar además de ver.

- [ ] **Step 5: Verificar en el navegador a 1440×900 y 390×844**

---

## Task 4: La ficha del Pokémon

**Files:**
- Create: `frontend/app/pokemon/[dex]/page.tsx`
- Create: `frontend/app/pokemon/[dex]/Ficha.tsx`
- Create: `frontend/app/pokemon/[dex]/Ficha.module.css`
- Modify: `frontend/app/lib/api.ts`

- [ ] **Step 1: La pantalla**

Tres bloques, en este orden, porque responde tres preguntas distintas y en ese orden de urgencia:

1. **Cabecera** — número de dex en la tipografía de datos, nombre en display, y cuántos ejemplares tienes.
2. **Tus ejemplares** — uno por fila. Tu foto si la hay; si no, el arte del catálogo, y lo dice. Set, número de colección, variante, condición, lo que pagaste y cuándo lo registraste. Si no tienes ninguno, el bloque invita a registrar en vez de mostrarse vacío.
3. **Rutas de caza** — las opciones del Excel con su arte y su precio, marcando cuál es la más barata. Cada una con la fecha del precio congelado.

Un botón "Registrar otro ejemplar" que lleva a `/registrar` con el dex ya puesto.

- [ ] **Step 2: Volver al binder**

Enlace de vuelta arriba, y que la página del binder desde la que veníamos siga siendo la misma al volver — el número de página vive en el estado del cliente, así que volver a `/` reinicia a la página 1. Aceptable por ahora; anotarlo si molesta.

- [ ] **Step 3: Estados degradados**

Un dex inexistente devuelve 404 y la pantalla lo dice con un enlace al binder. Sin backend, el mismo mensaje que ya usa la portada.

- [ ] **Step 4: Verificar registrando dos ejemplares distintos del mismo Pokémon**

Registrar dos Charmander de impresiones distintas, comprobar que ambos salen en la ficha, que el bolsillo muestra el apilado con `×2`, y que el contador del riel sube **uno solo**, no dos.

Borrar los ejemplares de prueba al terminar y confirmar que todo vuelve a cero.

---

## Verificación del plan completo

- [ ] Dos ejemplares distintos del mismo Pokémon conviven y se ven
- [ ] El bolsillo muestra tu carta, no la que perseguías, en cuanto tienes una
- [ ] El apilado y el `×N` aparecen solo con más de uno
- [ ] El progreso del 151 cuenta Pokémon, no cartas
- [ ] Una carta vendida no cuenta ni aparece
- [ ] Las fotos propias se sirven firmadas y el bucket sigue privado
- [ ] La suite pasa sin red

## Qué queda fuera

- Marcar cuál de tus ejemplares es "el del binder" frente a los duplicados: necesita `binder_id`/`page`, que nadie escribe todavía.
- Vender o dar de baja un ejemplar desde la UI: el estado existe en el esquema, la pantalla no.
- Precargar todas las impresiones existentes de un Pokémon: explícitamente no se hace, por pedido del dueño y porque el espejo perezoso ya evita justamente eso.
