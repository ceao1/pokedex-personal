# PRD — "Pokédex Viviente": web app personal de colección Pokémon TCG

**Autor:** Carlos · **Versión:** 0.2 (borrador para iteración) · **Fecha:** Agosto 2026
**Estado:** En definición — sin código aún

---

## 1. Visión y contexto

Aplicación web personal (móvil-first) para registrar, valorizar y ubicar la colección física de cartas Pokémon en inglés, centrada inicialmente en el proyecto "Pokédex viviente de los 151 originales". La app es el índice digital del binder físico: cada carta registrada sabe qué es (catálogo), cuánto costó (compra), dónde se consiguió (procedencia y geolocalización), dónde vive físicamente (binder/página/bolsillo) y cuánto vale hoy (mercado).

El diferencial frente a apps existentes (Collectr, TCG Collector, etc.) no es competir con ellas, sino tener control total de la data, el flujo de captura exacto que el dueño necesita (30 segundos, parado en una tienda de Lima o abriendo un paquete del forwarder), la lógica de costos de un inversionista (prorrateo de bundles, P&L real incluyendo envíos), y una base sobre la cual construir contenido build-in-public más adelante.

## 2. Objetivos

El MVP se considera exitoso si permite: registrar un ejemplar en menos de 30 segundos desde el celular con foto propia incluida; identificar la carta automáticamente desde la foto con confirmación manual; registrar compras tipo bundle con reparto de costo entre cartas; capturar el lugar de compra con un tap usando GPS cuando la fuente es física; responder "¿dónde está físicamente mi carta X?"; y mostrar el progreso del Pokédex 151 junto con el total invertido versus el valor de mercado actual.

**No-objetivos del MVP:** multiusuario, marketplace o venta, autenticación social, app nativa (será PWA), grading automático por foto, soporte de cartas en japonés, y scraping propio de precios.

## 3. Usuario y casos de uso

Usuario único: coleccionista adulto, técnico (data engineer), basado en Lima, que compra en tiendas físicas locales, eBay (Global Shipping) y vía casillero de Miami, con enfoque de presupuesto mensual y mentalidad de portfolio.

Casos de uso principales, en orden de frecuencia esperada: (1) registrar una carta recién comprada en tienda física; (2) registrar un lote/bundle llegado por forwarder; (3) registrar los pulls de un sobre abierto; (4) consultar el checklist para decidir qué cazar este mes; (5) consultar dónde está guardada una carta; (6) revisar el dashboard de progreso y P&L; (7) marcar cartas de la wishlist como "cazando" con precio objetivo.

## 4. Modelo de datos

El principio rector es la separación entre el catálogo (la carta como concepto) y el ejemplar (la copia física del usuario), con la compra como entidad intermedia que preserva la verdad del gasto original.

| Entidad | Descripción | Campos clave |
|---|---|---|
| **Card** (catálogo) | La carta como concepto, poblada desde la API de catálogo. Nunca se edita a mano salvo excepciones. | id externo (API), nombre, set, número de colección (ej. 199/165), rareza, imagen oficial (URL alta resolución), dex number del Pokémon, precios de mercado (cache) |
| **OwnedCopy** (ejemplar) | Una copia física en posesión. Puede haber N por Card. | card_id, purchase_id, variante (normal / reverse / holo / 1st Ed / Shadowless / Unlimited), condición (NM/LP/MP/HP/DMG), gradeada (sí/no, empresa, nota), fotos propias (frente/dorso), costo asignado, ubicación física (binder_id, página, bolsillo), estado (en binder / en tránsito / vendida), notas libres |
| **Purchase** (compra) | Evento de adquisición: 1 compra → N ejemplares. Preserva el costo total original. | fecha, tipo de fuente (tienda física / eBay / TCGplayer / intercambio / regalo / sobre), vendedor, URL del listing, precio total, costo de envío/forwarder, método de prorrateo usado, fotos del lote, place_id (si física), notas |
| **Place** (lugar) | Lugares de compra física, reutilizables. | nombre, ciudad, lat/lng, etiqueta ("Mi tienda de Miraflores"), frecuente (sí/no) |
| **Binder** | Contenedor físico. | nombre, descripción, capacidad por página |
| **WishlistItem** | Deseo sobre el catálogo, conectado al checklist. | card_id, estado (deseada / cazando / comprada-en-tránsito), precio objetivo, prioridad, mini-proyecto al que pertenece |
| **PriceSnapshot** (fase 2) | Histórico semanal de precios por Card. | card_id, fecha, precio market, fuente |

Ciclo de vida de una carta: `Deseada → Cazando (precio objetivo) → Comprada / En tránsito → En binder → (eventualmente) Vendida`. El estado "En tránsito" es relevante por los tiempos del casillero de Miami.

## 5. Funcionalidades del MVP

### 5.1 Catálogo poblado por API

El catálogo no se carga a mano. Al buscar una carta (por texto o por reconocimiento de foto), la app consulta TCGdex (idealmente self-hosted), cachea la ficha localmente (incluida la URL de imagen oficial) y la ofrece para vincular al ejemplar. El checklist de los 151 y la wishlist se siembran desde el Excel actual ("Pokedex_Viviente_151.xlsx") mediante un import inicial.

### 5.2 Flujo de captura móvil (la funcionalidad núcleo)

Requisito duro: registrar un ejemplar debe tomar menos de 30 segundos en un celular. Flujo pantalla a pantalla:

1. **Foto** del frente de la carta (cámara o galería).
2. **Identificación automática**: la foto va al servicio de reconocimiento; vuelve nombre, set, número y confianza. La app hace match determinístico contra el catálogo usando el número de colección (ej. "199/165" es casi llave única por set). Si la confianza es baja o hay `needsReview`, el ejemplar entra a una cola de revisión manual en lugar de guardarse con datos dudosos.
3. **Confirmación de variante**: chips de un tap (Normal / Reverse / Holo; para vintage: 1st Ed / Shadowless / Unlimited). Esta es la parte que ningún servicio automatiza con fiabilidad, por eso siempre la confirma el humano.
4. **Compra**: nueva o adjuntar a una compra existente (caso bundle). Precio, fuente.
5. **Ubicación**: si la fuente es física, botón "usar mi ubicación" (ver 5.4); si es online, campo para pegar el URL del listing.
6. **Guardar**. La ubicación en binder puede asignarse en el momento o después, en lote, desde desktop.

### 5.3 Compras y bundles (asignación de costos)

Una Purchase agrupa N ejemplares y ofrece tres métodos de reparto del costo total (precio + envío):

1. **Prorrateo por valor de mercado** (default): cada carta absorbe costo proporcional a su precio de mercado según la API. Ejemplo: lote de $95 con Haunter Fossil Holo ($40 de mercado, 57% → $54.30 asignado), Hitmonlee ($25, 36% → $33.90) y 10 commons ($5, 7% → $6.80).
2. **Manual**: el usuario escribe costos por carta y la app valida que la suma cuadre, mostrando el residuo en vivo.
3. **Partes iguales**: total ÷ cantidad, para lotes homogéneos.

Adicionales: opción de marcar cartas como **bulk/relleno con costo $0** (las cartas objetivo absorben todo el costo — refleja la realidad de "compré el lote por una carta" y mantiene el P&L honesto); el método de reparto es **recalculable después** sin perder el total original; los sobres se modelan como una Purchase cuyo costo se prorratea entre los pulls, habilitando la métrica "valor abierto vs. gastado en sobres".

### 5.4 Geolocalización del lugar de compra

Solo aplica a fuentes físicas. Flujo: tap en "usar mi ubicación" → permiso del navegador (Geolocation API) → captura de lat/lng → reverse geocoding → sugerencia de lugares cercanos como chips ("¿Estás en [tienda], Miraflores?") → un tap guarda etiqueta legible + coordenadas como Place. Lugares frecuentes quedan guardados para registro sin GPS. Fallback: extracción de GPS del EXIF de la foto si se registra después del momento de compra. Privacidad: la ubicación se captura únicamente al accionar el botón, nunca en background, y la data vive solo en la instancia del usuario.

Beneficio derivado: mapa de la colección (dónde se consiguió cada carta, incluyendo compras en viajes).

### 5.5 Ubicación física en binder

Cada ejemplar puede asignarse a binder → página → bolsillo. Vista de "binder virtual" (grilla de 9 bolsillos por página espejando el físico) como fase 1.5; en MVP basta el campo estructurado y la búsqueda "¿dónde está X?".

### 5.6 Dashboard

Progreso del Pokédex (X/151 con visual tipo grilla de dex), progreso por mini-proyecto (starters, línea Gengar, aves legendarias, etc.), total invertido (costo asignado real, incluyendo envíos) vs. valor de mercado actual, P&L absoluto y porcentual, costo promedio por carta, y gasto por mes contra el presupuesto mensual definido por el usuario.

### 5.7 Checklist y wishlist integrados

El checklist 151 y la "Galería de favoritos" (41 cartas objetivo de largo plazo) viven sobre el mismo catálogo, con estados del ciclo de vida y precio objetivo por carta. Import inicial desde el Excel existente.

## 6. Alternativas de servicios externos (decisión clave del PRD)

Existen tres familias de APIs que no deben confundirse: catálogo (input: nombre/ID de carta), precios (input: ID → output: valores de mercado) e imagen (input: foto → output: identidad de la carta). El MVP necesita una de catálogo + una de imagen; los precios pueden venir incluidos en la de catálogo.

### 6.1 API de catálogo

| Opción | Costo | Pros | Contras |
|---|---|---|---|
| ~~pokemontcg.io~~ | — | (Descartada) Era el estándar de facto | Adquirida por Scrydex; ya no ofrece free tier |
| **Scrydex** | Comercial, sin free tier | Sucesora de pokemontcg.io, SLA y soporte, incluye precios | Costo recurrente injustificable para uso personal |
| **TCGdex** ✅ | Gratis, open source | Multilingüe, self-hosteable (control total de la data y cero dependencia de terceros — natural para un data engineer), API REST y GraphQL, imágenes de cartas incluidas | Comunidad más pequeña; los precios de mercado deben verificarse y probablemente cubrirse con una API de precios aparte (§6.3) |

**Decisión:** **TCGdex**, idealmente self-hosted (su dataset es open source) para que el catálogo viva dentro de la propia infraestructura y no dependa de la disponibilidad de nadie. La capa de acceso queda igualmente abstraída (ports & adapters) por higiene. Consecuencia importante: TCGdex resuelve catálogo e imágenes, pero los precios de mercado pasan a depender de la API de precios (§6.3), que deja de ser opcional y se vuelve parte del MVP para el prorrateo por valor y el dashboard de P&L.

### 6.2 API de identificación por imagen

| Opción | Modelo | Pros | Contras |
|---|---|---|---|
| **CardVault Identify** | REST, foto → JSON; free tier | Devuelve nombre, set, número, rareza + confianza; devuelve `needsReview` honesto en vez de adivinar — ideal para cola de revisión | Servicio joven; verificar cobertura vintage |
| **CardGrader.AI** | REST, self-serve, créditos gratis de prueba; expone spec OpenAPI y servidor MCP | Identifica + predice grado tipo PSA + precia con comps reales en una pasada | Paga por scan; el grading es innecesario en MVP |
| **Ximilar** | API comercial, orientada a volumen | Veterano del rubro (ID, OCR, grading, pricing multi-TCG), muy preciso | Pricing enterprise, sobredimensionado para uso personal |
| **DIY: visión LLM (Claude/GPT)** | Foto → prompt → JSON estructurado | Centavos por scan al volumen personal; flexible: puede detectar sello 1st Edition, shadowless u otros atributos que las APIs no exponen; sin vendor lock-in | Hay que construir el prompt, el parsing y la validación; latencia algo mayor; sin garantías de accuracy |

**Recomendación:** enfoque híbrido. Empezar con **visión LLM** por costo y flexibilidad (especialmente por las variantes vintage), con validación estricta: el output solo se acepta si el número de colección extraído hace match exacto en el catálogo; todo lo demás va a revisión manual. Si la tasa de acierto en fotos reales (con brillo de sleeves, luz de tienda) decepciona, cambiar a CardVault por su manejo honesto de incertidumbre. La interfaz de reconocimiento se define como un puerto intercambiable desde el día uno.

### 6.3 API de precios (para P&L y prorrateo) — ahora parte del MVP

Con TCGdex como catálogo, los precios de mercado necesitan fuente propia. Candidatas: **JustTCG** (precios de mercado por carta vía API, orientada justo a este caso) y **PriceCharting** (fuerte en vintage y cartas gradeadas, relevante para las opciones 3 del checklist). Paso previo: verificar si la versión actual de TCGdex ya expone precios de TCGplayer/Cardmarket — si los trae, la API de precios vuelve a ser opcional. La elección final se hace comparando cobertura sobre una muestra de 20 cartas del checklist (10 modernas del 151, 10 vintage WOTC). Fase 2: pipeline propio de snapshots semanales (ver §8).

### 6.4 Reverse geocoding

| Opción | Costo | Nota |
|---|---|---|
| **Nominatim (OpenStreetMap)** | Gratis | Suficiente para "qué hay cerca"; límites de uso razonables para app personal |
| **Google Places API** | Free tier mensual, luego pago | Mejor detección de comercios (nombres de tiendas de TCG en Lima) |

**Recomendación:** Google Places para la sugerencia de tiendas (la calidad de POIs comerciales en Latinoamérica es notablemente mejor), dentro del free tier dado el volumen personal.

## 7. Requisitos no funcionales

Móvil-first como PWA instalable (la captura ocurre en el celular; la gestión, en desktop). Las fotos propias se almacenan en object storage (GCS es el hábitat natural del usuario) con thumbnails generados. Autenticación mínima de usuario único. Export completo de la data a CSV/Excel en cualquier momento (la data es del usuario, no de la app). Backup automático. Tolerancia offline básica en el flujo de captura: si no hay señal en la tienda, la foto y el borrador se encolan y se procesan al reconectar.

## 8. Fase 2 (post-MVP)

Histórico de precios propio: job semanal que snapshotea precios de toda la colección y wishlist (pipeline de datos simple, terreno natural). Alertas de precio objetivo sobre la wishlist. Página pública de la colección para build-in-public (progreso del dex, últimas adquisiciones, mapa). Estimación de condición/grado por foto (CardGrader.AI como candidato). Vista de binder virtual con drag & drop. Registro de ventas con P&L realizado vs. no realizado.

## 9. Métricas de éxito del MVP

Tiempo mediano de registro de un ejemplar < 30 segundos. Tasa de identificación automática correcta al primer intento > 85% en fotos reales (medible desde la cola de revisión). Cero cartas "perdidas": toda carta del binder físico existe en la app con ubicación. Uso sostenido: registro dentro de las 24 horas de cada adquisición durante 8 semanas consecutivas (la métrica que realmente predice si el sistema vive o muere).

## 10. Riesgos y decisiones abiertas

Riesgo principal: fricción de captura → mitigación: el flujo de 30 segundos es el requisito número uno y se prototipa primero. Riesgo del catálogo: cobertura de precios de TCGdex sin verificar → mitigación: catálogo self-hosted (elimina el riesgo de disponibilidad) + verificación temprana de precios con muestra de 20 cartas, con JustTCG/PriceCharting como plan B ya identificado. Riesgo de accuracy del reconocimiento con reflejos de holos/sleeves → mitigación: validación por número de colección + cola de revisión; decisión LLM vs. CardVault se toma con un piloto de 30 fotos reales tomadas en condiciones reales (tienda, casa, con sleeve). Decisión abierta: stack de implementación (fuera del alcance de este PRD; se decide al pasar a diseño técnico).

## 11. Roadmap sugerido

**Semana 1-2:** modelo de datos + TCGdex (deploy self-hosted o API pública) + verificación de cobertura de precios (muestra de 20 cartas, decisión sobre JustTCG/PriceCharting) + import del Excel. **Semana 3-4:** flujo de captura móvil con foto e identificación (piloto LLM con las 30 fotos de prueba). **Semana 5:** compras/bundles con prorrateo. **Semana 6:** geolocalización + ubicación en binder. **Semana 7-8:** dashboard, pulido, y las primeras 20 cartas reales registradas end-to-end.
