# Frontend: el binder viviente — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Una PWA en Next.js que muestre el Pokédex viviente de los 151 como lo que físicamente es —un binder de bolsillos de 3×3— leyendo del backend, y que se pueda abrir en `localhost` y recorrer.

**Architecture:** Next.js (App Router) con React Server Components para la carga inicial de datos desde FastAPI, y un cliente ligero para la navegación entre páginas del binder. Sin librería de componentes: el diseño es específico y una librería genérica lo aplanaría.

**Tech Stack:** Next.js 15, React 19, TypeScript, CSS Modules con custom properties, `next/font` para las tipografías.

**Spec:** `docs/superpowers/specs/2026-08-15-pokedex-viviente-design.md`
**Planes previos:** `2026-08-15-fundacion-y-catalogo.md`, `2026-08-15-checklist-151-e-import.md`

## Global Constraints

- **El backend es la única fuente de datos.** El frontend no habla con Supabase ni con TCGdex; solo con FastAPI en `http://127.0.0.1:8000`.
- **Móvil primero.** El caso real es el dueño parado en una tienda de Lima con el celular.
- **Piso de calidad, sin anunciarlo:** responsive hasta 360 px, foco de teclado visible, `prefers-reduced-motion` respetado, contraste AA en todo texto.
- **Copy en español**, sentence case, voz activa. Nada de "Submit" ni de jerga de sistema.
- **Sin librería de componentes** (ni MUI, ni Chakra, ni shadcn) y sin Tailwind: CSS Modules y custom properties.

---

## Dirección de diseño

El brief no fija estética, así que la fijo yo y la derivo del sujeto, no de un catálogo de plantillas.

**Sujeto:** el binder físico de un coleccionista que persigue los 151 originales en inglés. **Trabajo de la página:** mostrar de un vistazo cuánto falta y qué cazar. **El vacío es el contenido** — hoy hay 1 de 151, y la página tiene que hacer sentir esa distancia sin regañar.

### La tesis, y el riesgo que tomo

La respuesta de plantilla sería una grilla responsive infinita de tarjetas con esquinas redondeadas y un número grande arriba. La descarto.

**La página *es* una página de binder: nueve bolsillos, 3×3.** 151 Pokémon entran en 17 páginas de 9 bolsillos (153 casilleros, los dos últimos vacíos por aritmética, no por diseño). Se navega página por página, como se pasa un binder de verdad. La numeración no decora: dice dónde vive físicamente cada carta.

Ese es el riesgo — renunciar al scroll infinito, que es más cómodo de programar y más soso — y se justifica porque el producto entero existe para ser el índice de un objeto físico con esa forma exacta.

**Signature:** el bolsillo. Una funda translúcida con brillo de plástico en el borde superior; llena muestra el arte real de la carta, vacía muestra el número de dex en hueco y la silueta del Pokémon. El brillo solo se mueve al pasar el cursor sobre un bolsillo lleno — es la referencia al holo, gastada una sola vez.

### Tokens

**Color.** Ni crema con serif y terracota, ni negro con verde ácido. El binder de vinilo azul marino, con el rojo del Pokédex como acento escaso y el cian de la lente como luz de estado.

| Token | Hex | Uso |
|---|---|---|
| `--binder` | `#16233A` | Fondo: el vinilo del binder |
| `--binder-deep` | `#0E1727` | Lomo, sombras, fondo del riel |
| `--pocket` | `#1E2E49` | Cara del bolsillo vacío |
| `--sleeve-edge` | `#4A6591` | Borde de la funda, hairlines |
| `--stock` | `#F2EDE3` | Texto principal: cartón de carta |
| `--stock-dim` | `#93A3BE` | Texto secundario |
| `--shell` | `#E4572E` | Acento: la carcasa del Pokédex |
| `--lens` | `#4CC9F0` | Luz de estado "conseguido" |

Contraste: `--stock` sobre `--binder` da 12.8:1; `--stock-dim` sobre `--binder` da 5.6:1; `--shell` se usa solo en superficies grandes o texto ≥18 px.

**Tipografía.** Tres roles, ninguno de los habituales.

- **Display — Bricolage Grotesque, 800.** Proporciones ligeramente irregulares, con carácter; se usa solo en el título y en los números de página.
- **Datos — Martian Mono, 400/700.** Los números de dex, el contador y los precios. Es la referencia al contador de segmentos del aparato, y de paso alinea las columnas de cifras.
- **Cuerpo — Figtree, 400/600.** Nombres, etiquetas, todo lo demás.

Escala: `0.75 / 0.875 / 1 / 1.25 / 1.75 / 2.75 rem`, con `line-height` 1.15 en display y 1.5 en cuerpo.

**Layout.**

```
DESKTOP (>= 900px)
┌──────────────┬────────────────────────────────────────┐
│  RIEL        │   PÁGINA DEL BINDER                    │
│              │                                        │
│  Pokédex     │   ┌────────┬────────┬────────┐         │
│  viviente    │   │  001   │  002   │  003   │         │
│              │   │ [arte] │ vacío  │ vacío  │         │
│  001 / 151   │   ├────────┼────────┼────────┤         │
│  ▓░░░░░░░░░  │   │  004   │  005   │  006   │         │
│              │   │ vacío  │ vacío  │ vacío  │         │
│  ● conseguido│   ├────────┼────────┼────────┤         │
│  ● cazando   │   │  007   │  008   │  009   │         │
│  ○ falta     │   │ vacío  │ vacío  │ vacío  │         │
│              │   └────────┴────────┴────────┘         │
│  invertido   │                                        │
│  $0.00       │   ‹ anterior   página 1 de 17  siguiente ›│
└──────────────┴────────────────────────────────────────┘

MÓVIL (< 900px)
┌─────────────────────┐
│ Pokédex viviente    │
│ 001/151  ▓░░░░░░░░  │   ← riel colapsa a barra pegajosa
├─────────────────────┤
│ ┌────────┬────────┐ │   ← 2 columnas: el bolsillo sigue
│ │  001   │  002   │ │     siendo legible a 360px
│ │ [arte] │ vacío  │ │
│ ├────────┼────────┤ │
│ │  003   │  004   │ │
│ └────────┴────────┘ │
│ ‹  página 1 / 17  › │
└─────────────────────┘
```

En móvil el 3×3 se rompe a 2 columnas a propósito: forzar tres bolsillos en 360 px los dejaría ilegibles, y la fidelidad al objeto físico no vale sacrificar el caso de uso real. La agrupación por página de binder se mantiene, que es lo que de verdad codifica la ubicación.

**Motion.** Un solo momento orquestado: al cambiar de página, los nueve bolsillos entran escalonados 20 ms entre sí con un desplazamiento de 6 px. Nada más se mueve salvo el barrido de brillo en hover. Todo bajo `@media (prefers-reduced-motion: reduce)` se vuelve instantáneo.

### Revisión del plan contra el brief

Antes de escribir código, la prueba de la propia skill: ¿esto es lo que produciría para cualquier página parecida?

- **Fondo oscuro con acento** se parece de lejos al default nº 2, pero el acento no es un verde ácido decorativo: es el rojo de la carcasa del aparato y el cian de su lente, y el fondo es azul de vinilo, no negro. **Se mantiene.**
- **La grilla 3×3 paginada** no es un default de nada: los defaults son grillas responsive infinitas. **Se mantiene, es la firma.**
- **El contador grande arriba** sí era el default. **Cambiado:** el contador vive pequeño en el riel y el héroe es la página de binder con sus huecos.
- **Numeración 01/02/03 como adorno** está descartada por definición: aquí el número es el número de dex real y la posición en el bolsillo.

---

## Estructura de archivos

```
frontend/
  package.json
  next.config.ts
  tsconfig.json
  .env.local.example
  app/
    layout.tsx            # fuentes, metadata, PWA manifest
    page.tsx              # server component: trae /pokedex y renderiza el binder
    globals.css           # tokens y reset
    binder/
      Binder.tsx          # client: estado de página, teclado, motion
      Binder.module.css
      Pocket.tsx          # el bolsillo (lleno / vacío)
      Pocket.module.css
      Rail.tsx            # riel de progreso
      Rail.module.css
    lib/
      api.ts              # cliente tipado del backend
      types.ts
  public/
    manifest.webmanifest
    icon-192.png, icon-512.png
```

---

## Task 1: Scaffolding y tokens

**Files:**
- Create: `frontend/` (vía `create-next-app`)
- Create: `frontend/app/globals.css`
- Create: `frontend/app/layout.tsx`
- Create: `frontend/.env.local.example`
- Create: `frontend/app/lib/types.ts`
- Create: `frontend/app/lib/api.ts`

**Interfaces:**
- Produces: `Pokemon`, `WishlistItem`, `PokemonDetail` (tipos), `fetchPokedex()`, `fetchPokemon(dex)`

- [ ] **Step 1: Crear el proyecto**

```bash
cd /Users/carlosanzola/Documents/sandbox/pokedex
npx --yes create-next-app@latest frontend \
  --typescript --app --no-tailwind --no-eslint --no-src-dir \
  --import-alias "@/*" --use-npm --yes
```

Si `create-next-app` pregunta por Turbopack, aceptar el default.

- [ ] **Step 2: Escribir los tipos**

`frontend/app/lib/types.ts`:

```ts
export type Pokemon = {
  dex_number: number;
  name: string;
  wishlist_count: number;
  sin_resolver: number;
};

export type WishlistItem = {
  id: number;
  dex_number: number | null;
  card_id: string | null;
  variant_label: string | null;
  raw_text: string;
  source_option: string;
  auto_resolved: boolean;
  is_favorite: boolean;
  status: string;
  reference_value_usd: number | null;
  card_name: string | null;
  image_url: string | null;
  rarity: string | null;
  set_name: string | null;
  price_usd: number | null;
};

export type PokemonDetail = Pokemon & { options: WishlistItem[] };
```

- [ ] **Step 3: Escribir el cliente del backend**

`frontend/app/lib/api.ts`:

```ts
import type { Pokemon, PokemonDetail } from "./types";

const BASE_URL = process.env.API_BASE_URL ?? "http://127.0.0.1:8000";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`El backend respondió ${response.status} en ${path}`);
  }
  return response.json() as Promise<T>;
}

export function fetchPokedex(): Promise<Pokemon[]> {
  return get<Pokemon[]>("/pokedex");
}

export function fetchPokemon(dexNumber: number): Promise<PokemonDetail> {
  return get<PokemonDetail>(`/pokedex/${dexNumber}`);
}
```

`cache: "no-store"` porque la colección cambia cuando el dueño registra una carta, y una página cacheada que miente sobre el progreso es peor que una lenta.

`frontend/.env.local.example`:

```
API_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 4: Escribir los tokens y el reset**

`frontend/app/globals.css`:

```css
:root {
  --binder: #16233a;
  --binder-deep: #0e1727;
  --pocket: #1e2e49;
  --sleeve-edge: #4a6591;
  --stock: #f2ede3;
  --stock-dim: #93a3be;
  --shell: #e4572e;
  --lens: #4cc9f0;

  --step--1: 0.75rem;
  --step-0: 0.875rem;
  --step-1: 1rem;
  --step-2: 1.25rem;
  --step-3: 1.75rem;
  --step-4: 2.75rem;

  --gap: 0.75rem;
  --radius: 6px;
}

*,
*::before,
*::after {
  box-sizing: border-box;
}

* {
  margin: 0;
}

html {
  color-scheme: dark;
}

body {
  min-height: 100dvh;
  background: var(--binder);
  color: var(--stock);
  font-family: var(--font-body), system-ui, sans-serif;
  font-size: var(--step-1);
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

img {
  display: block;
  max-width: 100%;
}

button {
  font: inherit;
  color: inherit;
  background: none;
  border: none;
  cursor: pointer;
}

:focus-visible {
  outline: 2px solid var(--lens);
  outline-offset: 3px;
}

@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
  }
}
```

- [ ] **Step 5: Escribir el layout con las tres tipografías**

`frontend/app/layout.tsx`:

```tsx
import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Figtree, Martian_Mono } from "next/font/google";
import "./globals.css";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  weight: ["700", "800"],
  variable: "--font-display",
});

const body = Figtree({
  subsets: ["latin"],
  weight: ["400", "600"],
  variable: "--font-body",
});

const data = Martian_Mono({
  subsets: ["latin"],
  weight: ["400", "700"],
  variable: "--font-data",
});

export const metadata: Metadata = {
  title: "Pokédex viviente",
  description: "El índice digital de un binder físico de los 151 originales.",
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: "#16233a",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="es" className={`${display.variable} ${body.variable} ${data.variable}`}>
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 6: Verificar que arranca**

```bash
cd frontend && npm run dev
```
Expected: sirve en `http://localhost:3000` sin errores de compilación. Detenerlo después.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: scaffolding del frontend con tokens y tipografías"
```

---

## Task 2: El bolsillo

La pieza que carga todo el diseño. Se construye y se mira antes que nada más.

**Files:**
- Create: `frontend/app/binder/Pocket.tsx`
- Create: `frontend/app/binder/Pocket.module.css`

**Interfaces:**
- Produces: `<Pocket pokemon={Pokemon | null} slot={number} />`, donde `slot` es la posición 1-9 dentro de la página

- [ ] **Step 1: Escribir el componente**

`frontend/app/binder/Pocket.tsx`:

```tsx
import type { Pokemon } from "../lib/types";
import styles from "./Pocket.module.css";

type Props = {
  pokemon: Pokemon | null;
  index: number;
};

const ARTWORK = (dex: number) =>
  `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/other/official-artwork/${dex}.png`;

export function Pocket({ pokemon, index }: Props) {
  if (pokemon === null) {
    return <div className={`${styles.pocket} ${styles.blank}`} aria-hidden="true" />;
  }

  const conseguido = pokemon.wishlist_count > 0;

  return (
    <article
      className={styles.pocket}
      style={{ "--delay": `${index * 20}ms` } as React.CSSProperties}
    >
      <span className={styles.dex}>{String(pokemon.dex_number).padStart(3, "0")}</span>

      <div className={styles.art}>
        <img src={ARTWORK(pokemon.dex_number)} alt="" loading="lazy" />
      </div>

      <div className={styles.plate}>
        <h2 className={styles.name}>{pokemon.name}</h2>
        <span
          className={conseguido ? styles.lightOn : styles.lightOff}
          aria-label={conseguido ? "con rutas de caza" : "sin rutas"}
        />
      </div>

      <span className={styles.sheen} aria-hidden="true" />
    </article>
  );
}
```

La silueta usa el arte oficial de PokeAPI, que es estable y gratuito. Es la única excepción a "el backend es la única fuente de datos", y es deliberada: son ilustraciones del Pokémon, no datos de la colección.

- [ ] **Step 2: Escribir los estilos**

`frontend/app/binder/Pocket.module.css`:

```css
.pocket {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  aspect-ratio: 5 / 7;
  border-radius: var(--radius);
  background: linear-gradient(170deg, var(--pocket), var(--binder-deep));
  border: 1px solid color-mix(in srgb, var(--sleeve-edge) 45%, transparent);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--sleeve-edge) 60%, transparent),
    0 2px 8px rgb(0 0 0 / 0.35);
  overflow: hidden;
  animation: deal 260ms ease-out both;
  animation-delay: var(--delay, 0ms);
}

.blank {
  background: color-mix(in srgb, var(--binder-deep) 70%, transparent);
  border-style: dashed;
  box-shadow: none;
  animation: none;
}

.dex {
  font-family: var(--font-data), monospace;
  font-size: var(--step--1);
  letter-spacing: 0.08em;
  color: var(--stock-dim);
}

.art {
  flex: 1;
  display: grid;
  place-items: center;
  min-height: 0;
}

.art img {
  max-height: 100%;
  object-fit: contain;
  filter: drop-shadow(0 4px 10px rgb(0 0 0 / 0.45));
}

.plate {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid color-mix(in srgb, var(--sleeve-edge) 30%, transparent);
}

.name {
  font-size: var(--step-0);
  font-weight: 600;
  line-height: 1.2;
}

.lightOn,
.lightOff {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.lightOn {
  background: var(--lens);
  box-shadow: 0 0 8px var(--lens);
}

.lightOff {
  background: color-mix(in srgb, var(--sleeve-edge) 50%, transparent);
}

/* El barrido de brillo: la referencia al holo, gastada una sola vez. */
.sheen {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    115deg,
    transparent 35%,
    rgb(255 255 255 / 0.09) 48%,
    transparent 62%
  );
  translate: -110% 0;
  pointer-events: none;
}

.pocket:hover .sheen,
.pocket:focus-within .sheen {
  transition: translate 700ms ease-out;
  translate: 110% 0;
}

@keyframes deal {
  from {
    opacity: 0;
    translate: 0 6px;
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/app/binder
git commit -m "feat: el bolsillo del binder"
```

---

## Task 3: La página del binder y el riel

**Files:**
- Create: `frontend/app/binder/Binder.tsx`
- Create: `frontend/app/binder/Binder.module.css`
- Create: `frontend/app/binder/Rail.tsx`
- Create: `frontend/app/binder/Rail.module.css`
- Create: `frontend/app/page.tsx`

**Interfaces:**
- Consumes: `fetchPokedex()`, `<Pocket>`
- Produces: `<Binder pokedex={Pokemon[]} />`, `<Rail total, conseguidos, page, pages />`

- [ ] **Step 1: Escribir el riel**

`frontend/app/binder/Rail.tsx`:

```tsx
import styles from "./Rail.module.css";

type Props = {
  total: number;
  conseguidos: number;
  invertidoUsd: number;
};

export function Rail({ total, conseguidos, invertidoUsd }: Props) {
  const porcentaje = total === 0 ? 0 : Math.round((conseguidos / total) * 100);

  return (
    <aside className={styles.rail}>
      <header className={styles.brand}>
        <span className={styles.lens} aria-hidden="true" />
        <h1 className={styles.title}>
          Pokédex
          <br />
          viviente
        </h1>
      </header>

      <section className={styles.counter}>
        <p className={styles.count}>
          <span className={styles.have}>{String(conseguidos).padStart(3, "0")}</span>
          <span className={styles.of}>/{total}</span>
        </p>
        <div className={styles.bar}>
          <span className={styles.fill} style={{ inlineSize: `${porcentaje}%` }} />
        </div>
        <p className={styles.hint}>
          Te faltan {total - conseguidos} de los 151 originales.
        </p>
      </section>

      <section className={styles.money}>
        <p className={styles.moneyLabel}>Invertido</p>
        <p className={styles.moneyValue}>
          ${invertidoUsd.toFixed(2)} <span className={styles.usd}>USD</span>
        </p>
      </section>
    </aside>
  );
}
```

- [ ] **Step 2: Escribir los estilos del riel**

`frontend/app/binder/Rail.module.css`:

```css
.rail {
  display: flex;
  flex-direction: column;
  gap: 2rem;
  padding: 1.5rem;
  background: var(--binder-deep);
  border-right: 1px solid color-mix(in srgb, var(--sleeve-edge) 30%, transparent);
}

.brand {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

/* La lente redonda del aparato. Único uso del rojo de carcasa en grande. */
.lens {
  flex: none;
  width: 34px;
  height: 34px;
  border-radius: 50%;
  background: radial-gradient(circle at 32% 28%, #bff3ff, var(--lens) 42%, #1c6a8a);
  box-shadow:
    0 0 0 3px var(--shell),
    0 0 14px color-mix(in srgb, var(--lens) 50%, transparent);
}

.title {
  font-family: var(--font-display), sans-serif;
  font-weight: 800;
  font-size: var(--step-2);
  line-height: 1.05;
  letter-spacing: -0.02em;
}

.count {
  display: flex;
  align-items: baseline;
  gap: 0.25rem;
  font-family: var(--font-data), monospace;
}

.have {
  font-size: var(--step-3);
  font-weight: 700;
  color: var(--stock);
}

.of {
  font-size: var(--step-0);
  color: var(--stock-dim);
}

.bar {
  margin-block: 0.6rem 0.5rem;
  block-size: 6px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--sleeve-edge) 30%, transparent);
  overflow: hidden;
}

.fill {
  display: block;
  block-size: 100%;
  background: linear-gradient(90deg, var(--shell), var(--lens));
}

.hint,
.moneyLabel {
  font-size: var(--step-0);
  color: var(--stock-dim);
}

.moneyValue {
  font-family: var(--font-data), monospace;
  font-size: var(--step-2);
}

.usd {
  font-size: var(--step--1);
  color: var(--stock-dim);
}

@media (max-width: 899px) {
  .rail {
    position: sticky;
    top: 0;
    z-index: 2;
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.75rem 1rem;
    border-right: none;
    border-bottom: 1px solid color-mix(in srgb, var(--sleeve-edge) 30%, transparent);
  }

  .title,
  .hint,
  .money {
    display: none;
  }

  .bar {
    inline-size: 40vw;
    margin: 0;
  }

  .counter {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }
}
```

- [ ] **Step 3: Escribir el binder**

`frontend/app/binder/Binder.tsx`:

```tsx
"use client";

import { useState } from "react";
import type { Pokemon } from "../lib/types";
import { Pocket } from "./Pocket";
import { Rail } from "./Rail";
import styles from "./Binder.module.css";

const POR_PAGINA = 9;

export function Binder({ pokedex }: { pokedex: Pokemon[] }) {
  const [pagina, setPagina] = useState(0);
  const paginas = Math.ceil(pokedex.length / POR_PAGINA);

  const bolsillos: (Pokemon | null)[] = Array.from({ length: POR_PAGINA }, (_, i) => {
    return pokedex[pagina * POR_PAGINA + i] ?? null;
  });

  const conseguidos = pokedex.filter((p) => p.wishlist_count > 0).length;

  return (
    <div className={styles.shell}>
      <Rail total={pokedex.length} conseguidos={conseguidos} invertidoUsd={0} />

      <main className={styles.spread}>
        <div className={styles.grid} key={pagina}>
          {bolsillos.map((pokemon, i) => (
            <Pocket key={pokemon?.dex_number ?? `hueco-${i}`} pokemon={pokemon} index={i} />
          ))}
        </div>

        <nav className={styles.pager} aria-label="Páginas del binder">
          <button
            className={styles.turn}
            onClick={() => setPagina((p) => Math.max(0, p - 1))}
            disabled={pagina === 0}
          >
            ‹ Anterior
          </button>
          <p className={styles.pageNumber}>
            Página <b>{pagina + 1}</b> de {paginas}
          </p>
          <button
            className={styles.turn}
            onClick={() => setPagina((p) => Math.min(paginas - 1, p + 1))}
            disabled={pagina >= paginas - 1}
          >
            Siguiente ›
          </button>
        </nav>
      </main>
    </div>
  );
}
```

El `key={pagina}` en la grilla es lo que hace que React remonte los nueve bolsillos al cambiar de página y la animación escalonada vuelva a correr. Sin él, la página cambia sin que se note.

- [ ] **Step 4: Escribir los estilos del binder**

`frontend/app/binder/Binder.module.css`:

```css
.shell {
  display: grid;
  grid-template-columns: 240px 1fr;
  min-block-size: 100dvh;
}

.spread {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  padding: 2rem;
  max-inline-size: 900px;
  inline-size: 100%;
  margin-inline: auto;
}

.grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: var(--gap);
}

.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding-block-start: 0.5rem;
  border-top: 1px solid color-mix(in srgb, var(--sleeve-edge) 30%, transparent);
}

.turn {
  padding: 0.5rem 0.9rem;
  border-radius: var(--radius);
  border: 1px solid color-mix(in srgb, var(--sleeve-edge) 50%, transparent);
  font-size: var(--step-0);
  font-weight: 600;
  transition: background-color 140ms ease;
}

.turn:hover:not(:disabled) {
  background: color-mix(in srgb, var(--shell) 22%, transparent);
}

.turn:disabled {
  opacity: 0.35;
  cursor: not-allowed;
}

.pageNumber {
  font-family: var(--font-data), monospace;
  font-size: var(--step-0);
  color: var(--stock-dim);
}

.pageNumber b {
  color: var(--stock);
}

@media (max-width: 899px) {
  .shell {
    grid-template-columns: 1fr;
  }

  .spread {
    padding: 1rem;
  }

  .grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
```

- [ ] **Step 5: Escribir la página**

`frontend/app/page.tsx`:

```tsx
import { Binder } from "./binder/Binder";
import { fetchPokedex } from "./lib/api";

export default async function Home() {
  try {
    const pokedex = await fetchPokedex();
    if (pokedex.length === 0) {
      return (
        <main style={{ padding: "3rem", maxWidth: "42ch" }}>
          <h1>El binder está vacío</h1>
          <p>
            Corre el import del Excel para sembrar los 151:{" "}
            <code>uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx</code>
          </p>
        </main>
      );
    }
    return <Binder pokedex={pokedex} />;
  } catch {
    return (
      <main style={{ padding: "3rem", maxWidth: "42ch" }}>
        <h1>No hay conexión con el backend</h1>
        <p>
          Levanta FastAPI en el puerto 8000:{" "}
          <code>cd backend && uv run uvicorn pokedex.api.main:app --app-dir src</code>
        </p>
      </main>
    );
  }
}
```

Los dos estados degradados dicen qué pasó y qué comando lo arregla. Una pantalla vacía sin instrucción sería una pared.

- [ ] **Step 6: Verificar en el navegador**

Con el backend corriendo y el import hecho:

```bash
cd frontend && npm run dev
```

Abrir `http://localhost:3000`. Expected: la primera página del binder con Bulbasaur a Squirtle, el riel con el contador, y el paginador diciendo "Página 1 de 17".

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: la página del binder con su riel de progreso"
```

---

## Task 4: PWA, accesibilidad y pulido responsive

**Files:**
- Create: `frontend/public/manifest.webmanifest`
- Create: `frontend/public/icon-192.png`, `frontend/public/icon-512.png`
- Modify: `frontend/app/binder/Binder.tsx` (navegación por teclado)

- [ ] **Step 1: Escribir el manifest**

`frontend/public/manifest.webmanifest`:

```json
{
  "name": "Pokédex viviente",
  "short_name": "Pokédex",
  "start_url": "/",
  "display": "standalone",
  "background_color": "#16233a",
  "theme_color": "#16233a",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

- [ ] **Step 2: Generar los íconos**

Generar dos PNG cuadrados con la lente sobre el fondo `#16233a` usando Python:

```bash
cd /Users/carlosanzola/Documents/sandbox/pokedex/backend
uv run --with pillow python - <<'PY'
from PIL import Image, ImageDraw
for size in (192, 512):
    img = Image.new("RGB", (size, size), "#16233a")
    d = ImageDraw.Draw(img)
    r = size * 0.30
    c = size / 2
    d.ellipse([c - r - size * 0.035, c - r - size * 0.035,
               c + r + size * 0.035, c + r + size * 0.035], fill="#e4572e")
    d.ellipse([c - r, c - r, c + r, c + r], fill="#4cc9f0")
    d.ellipse([c - r * 0.55, c - r * 0.75, c - r * 0.05, c - r * 0.25], fill="#bff3ff")
    img.save(f"../frontend/public/icon-{size}.png")
print("listo")
PY
```

- [ ] **Step 3: Navegación por teclado entre páginas**

En `Binder.tsx`, añadir dentro del componente:

```tsx
  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "ArrowLeft") setPagina((p) => Math.max(0, p - 1));
      if (event.key === "ArrowRight") setPagina((p) => Math.min(paginas - 1, p + 1));
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [paginas]);
```

(y añadir `useEffect` al import de React)

- [ ] **Step 4: Verificar el piso de calidad**

- Reducir la ventana a 360 px de ancho: dos columnas, nada se desborda horizontalmente.
- Tabular con el teclado: el foco se ve en los botones del paginador con el contorno cian.
- Activar "reducir movimiento" en el sistema: los bolsillos aparecen sin animación.
- Flechas izquierda y derecha cambian de página.

- [ ] **Step 5: Commit**

```bash
git add frontend
git commit -m "feat: PWA instalable, teclado y responsive"
```

---

## Task 5: cartas reales en los bolsillos

Corrige dos cosas de las tasks anteriores. La primera es un defecto de honestidad: el riel calculaba el progreso como `wishlist_count > 0`, y después del import del Excel eso da 151 de 151 — la app diría que la colección está completa sin una sola carta registrada. La segunda es una mejora que el backend ahora habilita: el bolsillo puede mostrar el arte real de la carta TCG que se persigue en vez de un sprite genérico.

**Files:**
- Modify: `frontend/app/lib/types.ts`
- Modify: `frontend/app/binder/Pocket.tsx`
- Modify: `frontend/app/binder/Pocket.module.css`
- Modify: `frontend/app/binder/Rail.tsx`
- Modify: `frontend/app/binder/Rail.module.css`
- Modify: `frontend/app/binder/Binder.tsx`

**Interfaces:**
- Consumes: los campos nuevos de `GET /pokedex` — `owned_count`, `primary_image_url`, `primary_card_name`, `primary_price_usd`

- [ ] **Step 1: Ampliar el tipo**

En `frontend/app/lib/types.ts`, el tipo `Pokemon` pasa a:

```ts
export type Pokemon = {
  dex_number: number;
  name: string;
  wishlist_count: number;
  sin_resolver: number;
  owned_count: number;
  primary_image_url: string | null;
  primary_card_name: string | null;
  primary_price_usd: number | null;
};
```

- [ ] **Step 2: Reescribir el bolsillo**

`frontend/app/binder/Pocket.tsx`:

```tsx
import type { Pokemon } from "../lib/types";
import styles from "./Pocket.module.css";

type Props = {
  pokemon: Pokemon | null;
  index: number;
};

export function Pocket({ pokemon, index }: Props) {
  if (pokemon === null) {
    return <div className={`${styles.pocket} ${styles.blank}`} aria-hidden="true" />;
  }

  const conseguido = pokemon.owned_count > 0;
  const dex = String(pokemon.dex_number).padStart(3, "0");

  return (
    <article
      className={`${styles.pocket} ${conseguido ? styles.owned : styles.hunting}`}
      style={{ "--delay": `${index * 20}ms` } as React.CSSProperties}
      aria-label={
        conseguido
          ? `${pokemon.name}, número ${dex}, en el binder`
          : `${pokemon.name}, número ${dex}, todavía no lo tienes`
      }
    >
      {pokemon.primary_image_url ? (
        <img
          className={styles.card}
          src={pokemon.primary_image_url}
          alt=""
          loading="lazy"
        />
      ) : (
        <div className={styles.noCard}>
          <span>Sin carta asignada</span>
        </div>
      )}

      <span className={styles.sheen} aria-hidden="true" />

      <footer className={styles.plate}>
        <span className={styles.dex}>{dex}</span>
        <span className={styles.name}>{pokemon.name}</span>
        {pokemon.primary_price_usd !== null && (
          <span className={styles.price}>${pokemon.primary_price_usd.toFixed(2)}</span>
        )}
      </footer>
    </article>
  );
}
```

El arte de la carta ya es 5:7, la misma proporción del bolsillo, así que llena el hueco sin recortes. La placa inferior flota encima, como la etiqueta de una funda.

- [ ] **Step 3: Reescribir los estilos del bolsillo**

`frontend/app/binder/Pocket.module.css`:

```css
.pocket {
  position: relative;
  display: block;
  aspect-ratio: 5 / 7;
  border-radius: var(--radius);
  background: linear-gradient(170deg, var(--pocket), var(--binder-deep));
  border: 1px solid color-mix(in srgb, var(--sleeve-edge) 45%, transparent);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--sleeve-edge) 60%, transparent),
    0 2px 8px rgb(0 0 0 / 0.35);
  overflow: hidden;
  animation: deal 260ms ease-out both;
  animation-delay: var(--delay, 0ms);
}

.blank {
  background: color-mix(in srgb, var(--binder-deep) 70%, transparent);
  border-style: dashed;
  box-shadow: none;
  animation: none;
}

.card {
  inline-size: 100%;
  block-size: 100%;
  object-fit: cover;
}

/* El binder se llena de color a medida que la colección crece: lo que
   todavía no tienes se ve como una carta guardada detrás del plástico. */
.hunting .card {
  filter: grayscale(0.75) brightness(0.62) contrast(0.95);
}

.owned {
  border-color: color-mix(in srgb, var(--lens) 55%, transparent);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--lens) 40%, transparent),
    0 0 0 1px color-mix(in srgb, var(--lens) 25%, transparent),
    0 4px 14px rgb(0 0 0 / 0.45);
}

.noCard {
  display: grid;
  place-items: center;
  block-size: 100%;
  padding: 1rem;
  text-align: center;
  font-size: var(--step--1);
  color: var(--stock-dim);
}

.plate {
  position: absolute;
  inset-inline: 0;
  inset-block-end: 0;
  display: flex;
  align-items: baseline;
  gap: 0.4rem;
  padding: 0.55rem 0.6rem;
  background: linear-gradient(to top, rgb(6 11 20 / 0.94), rgb(6 11 20 / 0));
}

.dex {
  font-family: var(--font-data), monospace;
  font-size: var(--step--1);
  color: var(--stock-dim);
}

.name {
  flex: 1;
  min-inline-size: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--step-0);
  font-weight: 600;
}

.price {
  font-family: var(--font-data), monospace;
  font-size: var(--step--1);
  color: var(--shell);
}

.sheen {
  position: absolute;
  inset: 0;
  background: linear-gradient(
    115deg,
    transparent 35%,
    rgb(255 255 255 / 0.11) 48%,
    transparent 62%
  );
  translate: -110% 0;
  pointer-events: none;
}

.pocket:hover .sheen,
.pocket:focus-within .sheen {
  transition: translate 700ms ease-out;
  translate: 110% 0;
}

@keyframes deal {
  from {
    opacity: 0;
    translate: 0 6px;
  }
}
```

- [ ] **Step 4: Corregir el riel**

En `frontend/app/binder/Rail.tsx`, la sección de dinero deja de mostrar un "Invertido $0.00" que no significa nada y pasa a mostrar lo que cuesta completar el proyecto, que es un dato real y útil. Reemplazar la firma y la sección:

```tsx
type Props = {
  total: number;
  conseguidos: number;
  costoRestanteUsd: number;
};
```

```tsx
      <section className={styles.money}>
        <p className={styles.moneyLabel}>Completar el 151</p>
        <p className={styles.moneyValue}>
          ${costoRestanteUsd.toFixed(2)} <span className={styles.usd}>USD</span>
        </p>
        <p className={styles.hint}>Sumando la ruta más económica de cada uno.</p>
      </section>
```

- [ ] **Step 5: Corregir el cálculo del progreso**

En `frontend/app/binder/Binder.tsx`, reemplazar el cálculo de `conseguidos` y pasar el costo:

```tsx
  const conseguidos = pokedex.filter((p) => p.owned_count > 0).length;
  const costoRestante = pokedex
    .filter((p) => p.owned_count === 0)
    .reduce((total, p) => total + (p.primary_price_usd ?? 0), 0);
```

```tsx
      <Rail total={pokedex.length} conseguidos={conseguidos} costoRestanteUsd={costoRestante} />
```

`owned_count` y no `wishlist_count`: tener una ruta de caza no es tener la carta, y confundirlas hacía que el contador dijera 151 de 151 apenas se importaba el Excel.

- [ ] **Step 6: Verificar**

Con el backend arriba y el import hecho, abrir `http://localhost:3000`:
- El contador dice `000 / 151`, no `151 / 151`.
- Los bolsillos muestran arte de cartas TCG reales, apagadas en gris.
- Cada bolsillo lleva su número, su nombre y su precio.
- El costo de completar el 151 es una cifra distinta de cero.

- [ ] **Step 7: Commit**

```bash
git add frontend
git commit -m "feat: cartas reales en los bolsillos y progreso honesto"
```

---

## Verificación del plan completo

- [ ] `http://localhost:3000` muestra 17 páginas de binder con los 151
- [ ] El contador del riel refleja los datos reales del backend
- [ ] A 360 px no hay scroll horizontal
- [ ] El foco de teclado es visible y las flechas pasan página
- [ ] Con "reducir movimiento" activo no hay animaciones
- [ ] Con el backend apagado, la página explica cómo levantarlo en vez de reventar

## Qué queda fuera

- Vista de detalle de un Pokémon con sus cuatro opciones: el endpoint existe, la pantalla llega después
- Registro de cartas, fotos y captura: necesitan el plan 3 del backend y una llave de API de visión
- Modo claro: el binder es un objeto oscuro; un tema claro sería otra dirección de diseño, no una variante
