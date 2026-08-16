# Identificación de cartas por foto — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la foto de una carta rellene sola el set y el número, para que registrar sea confirmar en vez de teclear.

**Architecture:** Un `RecognitionPort` con un adaptador de Gemini. La respuesta del modelo **nunca** se acepta tal cual: solo vale si el número de colección que leyó existe de verdad en el catálogo. Todo lo demás va a revisión manual, que es el camino que ya funciona hoy.

**Tech Stack:** El mismo, más la API de Gemini (`generativelanguage.googleapis.com`) por HTTP con `httpx`. Sin SDK nuevo.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md` §5.2 y §6.2

## Hechos verificados contra la API real

Probado con la llave que el dueño dejó en `backend/.env` como `GEMINI_API`:

- La llave es del tipo AI Studio: se envía como `?key=`, **no** como `Authorization: Bearer` (eso devuelve 401).
- `gemini-2.0-flash` ya no existe (404). `gemini-3.5-flash` sí y es el que usa este plan.
- Con el arte de `base1-4` y `responseMimeType: application/json` devolvió, en 5.5 s y 1185→66 tokens:
  ```json
  {"name":"Charizard","set_name":"Base Set","number":"4/102",
   "rarity":"Rare Holo","confidence":0.99,"needs_review":false}
  ```
- `GET /v2/en/sets` de TCGdex devuelve **218 sets** con `{id, name, cardCount}` y **cero nombres duplicados**, así que el nombre de set que devuelve el modelo se puede mapear a un id sin ambigüedad.

Ese `number` con formato `4/102` es la pieza clave: es exactamente lo que el spec exige para validar.

## Global Constraints

- **La respuesta del modelo no se cree.** Solo se acepta si `(set, número)` resuelve a una carta real del catálogo. Spec §5.2: *"Si la confianza es baja o hay `needsReview`, el ejemplar entra a una cola de revisión manual en lugar de guardarse con datos dudosos."*
- **La variante siempre la confirma el humano.** Spec §5.2: es la parte que ningún servicio automatiza con fiabilidad. El modelo no la elige.
- **La llave nunca sale del backend.** El navegador no la ve ni la usa.
- **Ningún test de la suite por defecto puede pegarle a la red.** Los tests usan un `RecognitionPort` falso. Los que llamen a Gemini de verdad llevan `@pytest.mark.contract`, igual que los de TCGdex.
- **Moneda única USD**, `Decimal` en Python.
- **Copy en español**, sentence case, voz activa.

---

## Task 1: El puerto y el adaptador de Gemini

**Files:**
- Create: `backend/src/pokedex/recognition/__init__.py`
- Create: `backend/src/pokedex/recognition/models.py`
- Create: `backend/src/pokedex/recognition/ports.py`
- Create: `backend/src/pokedex/recognition/gemini.py`
- Modify: `backend/src/pokedex/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/recognition/test_gemini.py`
- Test: `backend/tests/recognition/test_gemini_contract.py`
- Create: `backend/tests/recognition/__init__.py`

**Interfaces:**
- `models.Recognition` — `name: str | None`, `set_name: str | None`, `number: str | None`, `rarity: str | None`, `confidence: float`, `needs_review: bool`, `raw: dict`
- `ports.RecognitionPort` (Protocol) — `async identify(image: bytes, mime_type: str) -> Recognition`
- `gemini.GeminiRecognition(api_key, model, client)` que lo implementa
- `gemini.FakeRecognition` para tests

- [ ] **Step 1: Ampliar la configuración**

En `config.py`:

```python
    gemini_api: str = ""
    gemini_model: str = "gemini-3.5-flash"
```

El nombre `gemini_api` coincide con la variable que el dueño ya puso en su `.env`. En `.env.example`, documentarla con un comentario diciendo que sin ella la identificación se apaga sola y el registro sigue funcionando a mano.

- [ ] **Step 2: Escribir los tests con `respx` (que van a fallar)**

Casos obligatorios, todos sin red:

- Una respuesta bien formada se parsea a `Recognition` con sus seis campos.
- El modelo devuelve JSON envuelto en ```` ```json ```` — se parsea igual. Los modelos lo hacen aunque se les pida lo contrario.
- El modelo devuelve texto que no es JSON — `Recognition` con `needs_review=True` y `confidence=0.0`, **sin lanzar excepción**. Una carta mal leída no puede tumbar el registro.
- La API responde 429 o 5xx — se propaga como error, no se disfraza de "no reconocida". Son cosas distintas: una es "no sé qué carta es", la otra es "no pude preguntar", y la segunda merece reintento.
- La llave viaja como `?key=`, nunca en una cabecera `Authorization` (verificado: Bearer da 401).
- La imagen viaja en `inline_data` con su `mime_type`.

- [ ] **Step 3: Escribir el adaptador**

`gemini.py` construye la petición a
`https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}`
con `temperature: 0` y `responseMimeType: "application/json"`, y un prompt que pide exactamente las seis claves.

El prompt debe decirle al modelo que **es preferible admitir duda que inventar**: si no puede leer el número con certeza, `number: null`, confianza baja y `needs_review: true`. Un número inventado que casualmente existe en el catálogo es el peor resultado posible, porque pasaría la validación.

- [ ] **Step 4: Test de contrato contra Gemini real**

En `test_gemini_contract.py`, con `pytestmark = pytest.mark.contract`: descargar `base1-4` del CDN de TCGdex, identificarla, y comprobar que devuelve `Charizard` y un número que contiene `4/102`. Es la alarma de que el modelo o el formato cambiaron.

Un solo test, una sola llamada: cuesta dinero real del dueño.

- [ ] **Step 5: Correr, formatear y commitear**

---

## Task 2: Validar contra el catálogo

Aquí es donde la respuesta del modelo se gana el derecho a ser creída.

**Files:**
- Create: `backend/src/pokedex/recognition/resolver.py`
- Modify: `backend/src/pokedex/catalog/ports.py` y `tcgdex.py` (listar sets)
- Test: `backend/tests/recognition/test_resolver.py`

**Interfaces:**
- `CatalogPort.list_sets() -> list[SetRef]` con `SetRef(id, name, total)`
- `resolver.CardResolver(catalog)` con `async resolver(reconocido: Recognition) -> ResolucionCarta`
- `ResolucionCarta` — `card: Card | None`, `motivo: str`, `necesita_revision: bool`

- [ ] **Step 1: Escribir los tests (que van a fallar)**

La tabla de casos, que es el corazón de esta task:

| Lo que devuelve el modelo | Resultado esperado |
|---|---|
| `set_name` "Base Set", `number` "4/102" | resuelve a `base1-4` |
| `number` "004/102" (con ceros) | resuelve igual: el número se normaliza |
| `set_name` "base set" en minúsculas | resuelve igual: el nombre se compara sin distinguir mayúsculas |
| `set_name` que no existe en TCGdex | sin carta, `necesita_revision`, motivo explícito |
| `number` cuyo denominador no cuadra con el `cardCount` del set | sin carta: el modelo se contradijo a sí mismo |
| número que no existe en ese set | sin carta, `necesita_revision` |
| `needs_review: true` del propio modelo | sin carta, aunque el número resolviera |
| `confidence` por debajo del umbral | sin carta, aunque el número resolviera |
| el nombre del modelo no coincide con el de la carta encontrada | sin carta: dos señales que se contradicen no son una confirmación |

Ese último caso importa: si el modelo dice "Charizard" y el número apunta a un Squirtle, algo está mal y adivinar cuál de las dos señales vale sería inventar.

- [ ] **Step 2: Ampliar el puerto de catálogo**

`list_sets()` sobre `GET /v2/en/sets`, cacheado en memoria como ya hace `list_set_cards`. Son 218 sets con nombres únicos (verificado), así que un diccionario nombre-normalizado → id basta.

- [ ] **Step 3: Escribir el resolutor**

Umbral de confianza como constante nombrada con un comentario que diga de dónde sale. Empezar en `0.7` y anotar que es un número elegido, no medido: solo un piloto con fotos reales puede calibrarlo, y el spec ya lo pide.

La comparación de nombres tolera diferencias de mayúsculas, acentos y sufijos como `ex` o `V`, pero **no** hace coincidencias parciales agresivas. Ante la duda, revisión manual.

- [ ] **Step 4: Correr y commitear**

---

## Task 3: El endpoint de identificación

**Files:**
- Modify: `backend/src/pokedex/api/routes/capture.py`
- Modify: `backend/src/pokedex/collection/service.py`
- Test: `backend/tests/api/test_capture_routes.py`

**Interfaces:**
- `POST /captures/{client_draft_id}/identificar` → `{ reconocido, carta, necesita_revision, motivo }`

- [ ] **Step 1: Escribir los tests**

Con un `RecognitionPort` falso: identifica y devuelve la carta; con confianza baja devuelve `necesita_revision` y ninguna carta; sin llave configurada devuelve 503 con un mensaje que dice que la identificación está apagada y que se puede registrar a mano.

- [ ] **Step 2: Implementar**

El endpoint descarga la foto del ejemplar desde Storage con una URL firmada, la pasa al `RecognitionPort`, valida con el `CardResolver` y devuelve el resultado. **No escribe nada en `owned_copy`**: la decisión sigue siendo del humano, y escribir antes de que confirme es exactamente lo que el spec prohíbe.

Si la resolución tiene éxito, espeja la carta —el mismo `_asegurar_espejo` que ya existe— para que el cliente reciba su arte y su precio.

Sin `gemini_api` configurada, el endpoint responde 503 y **nada más se rompe**: el registro manual sigue igual.

- [ ] **Step 3: Correr y commitear**

---

## Task 4: La pantalla propone y el humano confirma

**Files:**
- Modify: `frontend/app/registrar/Captura.tsx`
- Modify: `frontend/app/registrar/Captura.module.css`
- Modify: `frontend/app/lib/api.ts` y `types.ts`

- [ ] **Step 1: Llamar a identificar cuando la foto termina de subir**

En cuanto la subida se confirma, se dispara la identificación en segundo plano. **No bloquea nada**: el dueño puede seguir escribiendo el número a mano mientras tanto, y si termina antes, gana lo que él escribió.

- [ ] **Step 2: Mostrar la propuesta, no imponerla**

Cuando vuelve con carta:

- Se muestra el arte encontrado, el nombre, el set y el número.
- El texto dice que es una propuesta y de dónde viene, algo como *"Reconocida por la foto — confirma que es esta"*.
- Un botón la acepta y rellena set y número. **Los campos no se rellenan solos**: aceptar es un acto del dueño, y así una identificación equivocada nunca se cuela por inercia.
- Si el dueño ya escribió un número distinto, la propuesta no lo pisa; se muestra al lado y él decide.

Cuando vuelve sin carta, lo dice en una línea con el motivo, sin alarmismo: *"No pude leer el número. Escríbelo tú."* La identificación fallida es un caso normal, no un error.

- [ ] **Step 3: Los chips de variante siguen siendo del humano**

Sin cambios: el modelo no propone variante. Es la parte que el spec dice explícitamente que no se automatiza con fiabilidad, y el precio depende de ella.

- [ ] **Step 4: Verificar en el celular con una carta física de verdad**

Fotografiar una carta real, comprobar que propone la correcta, aceptarla, guardar, y ver el bolsillo pasar a color. Medir cuánto tarda el flujo completo. Borrar el ejemplar de prueba al terminar.

---

## Verificación del plan completo

- [ ] Una foto de una carta real propone la carta correcta
- [ ] Una propuesta equivocada o dudosa no se guarda sola nunca
- [ ] Sin llave configurada, la app entera sigue funcionando a mano
- [ ] La llave no aparece jamás en una respuesta ni en el bundle del navegador
- [ ] La suite pasa sin red; el test de contrato pasa con red
- [ ] El registro sigue tomando menos de 30 segundos

## Qué queda fuera

- Detectar la variante por foto: el spec lo excluye a propósito y el precio depende de acertarla.
- Estimar la condición o el grado: fase 2 del spec.
- Reintentos y cola persistente de identificación: una llamada por foto, y el dueño puede repetirla. Si el volumen lo pide, la tabla `job` del spec es el sitio.
