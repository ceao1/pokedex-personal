#!/usr/bin/env bash
# Levanta el Pokédex viviente en local: Supabase, el backend y el frontend.
#
#   ./run-dev.sh          arranca todo
#   ./run-dev.sh --import arranca todo y siembra el checklist desde el Excel
#
# Ctrl-C detiene el backend y el frontend. Supabase queda corriendo: bajarlo
# con `supabase stop` cuando termines la sesión.

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=3000
EXCEL="$RAIZ/Pokedex_Viviente_151.xlsx"

info() { printf '\033[36m▸\033[0m %s\n' "$*"; }
aviso() { printf '\033[33m!\033[0m %s\n' "$*"; }
error() { printf '\033[31m✗\033[0m %s\n' "$*" >&2; }

limpiar() {
  info "Deteniendo…"
  # Matar el grupo de procesos de cada hijo: `next dev` levanta workers.
  [[ -n "${PID_BACKEND:-}" ]] && kill "$PID_BACKEND" 2>/dev/null || true
  [[ -n "${PID_FRONTEND:-}" ]] && kill "$PID_FRONTEND" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap limpiar EXIT INT TERM

# --- Supabase ----------------------------------------------------------------
if ! supabase status >/dev/null 2>&1; then
  info "Levantando Supabase (necesita Docker corriendo)…"
  supabase start >/dev/null
fi
info "Supabase arriba: base en 54322, Studio en http://127.0.0.1:54323"

# --- Backend -----------------------------------------------------------------
# `--app-dir src` no es opcional: macOS marca como ocultos los .pth de la
# instalación editable y Python salta los .pth ocultos, así que sin esto el
# paquete `pokedex` no resuelve.
info "Arrancando el backend en :$BACKEND_PORT…"
(
  cd "$RAIZ/backend"
  exec uv run uvicorn pokedex.api.main:app --app-dir src --port "$BACKEND_PORT"
) &
PID_BACKEND=$!

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

if ! curl -sf "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
  error "El backend no respondió en /health. Revisa la salida de arriba."
  exit 1
fi
info "Backend listo: http://127.0.0.1:$BACKEND_PORT"

# --- Import opcional ---------------------------------------------------------
if [[ "${1:-}" == "--import" ]]; then
  info "Sembrando el checklist desde el Excel (tarda: espeja cientos de cartas)…"
  # PYTHONPATH=src y no la instalación editable: macOS marca como ocultos los
  # .pth de site-packages y Python salta los .pth ocultos. pytest lo sortea con
  # `pythonpath` y uvicorn con `--app-dir`; `python -m` no tiene escape posible,
  # porque resuelve el paquete antes de ejecutar una sola línea suya.
  ( cd "$RAIZ/backend" && PYTHONPATH=src uv run python -m pokedex.cli import-excel "$EXCEL" )
fi

POKEMON=$(psql "postgresql://postgres:postgres@127.0.0.1:54322/postgres" -tAc \
  "select count(*) from app.pokemon" 2>/dev/null || echo 0)
if [[ "$POKEMON" -eq 0 ]]; then
  aviso "El checklist está vacío. Corre ./run-dev.sh --import para sembrarlo."
else
  info "Checklist sembrado: $POKEMON Pokémon."
fi

# --- Frontend ----------------------------------------------------------------
info "Arrancando el frontend en :$FRONTEND_PORT…"
(
  cd "$RAIZ/frontend"
  exec npm run dev -- --port "$FRONTEND_PORT"
) &
PID_FRONTEND=$!

for _ in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$FRONTEND_PORT" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

printf '\n\033[32m●\033[0m Pokédex viviente en \033[1mhttp://localhost:%s\033[0m\n' "$FRONTEND_PORT"
printf '  API      http://127.0.0.1:%s/docs\n' "$BACKEND_PORT"
printf '  Studio   http://127.0.0.1:54323\n\n'
printf '  Ctrl-C para detener.\n\n'

wait
