"""Comandos de línea de comandos.

uv run python -m pokedex.cli sembrar
"""

import sys
from pathlib import Path

# macOS a veces marca como oculto (`UF_HIDDEN`) el .pth de la instalación
# editable, y `site.py` ignora los .pth ocultos al armar `sys.path` al
# arrancar el intérprete -- el mismo problema que forzó `pythonpath =
# ["src"]` en la config de pytest y `--app-dir src` en la invocación de
# uvicorn (ver los comentarios ahí). pytest y uvicorn tienen su propio
# escape hatch para insertar `src`; un `python` o `python -m` liso no tiene
# ninguno, así que se agrega acá. No borrar pensando que es dead code:
# cubre invocar este archivo directamente como script (donde Python no
# necesita resolver el paquete `pokedex` para arrancar, pero sí lo
# necesitan los `from pokedex...` de abajo). Para `-m pokedex.cli` el
# problema es anterior a esta línea -- Python tiene que resolver el
# paquete `pokedex` antes de ejecutar una sola línea de este archivo -- y
# se corrige reparando el `.pth` (`chflags nohidden` sobre el archivo
# marcado oculto en `site-packages`), no con código.
if "pokedex" not in sys.modules:
    try:
        import pokedex  # noqa: F401
    except ModuleNotFoundError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import argparse  # noqa: E402
import asyncio  # noqa: E402

import httpx  # noqa: E402

from pokedex.catalog.service import CatalogService  # noqa: E402
from pokedex.catalog.tcgdex import TcgdexCatalog  # noqa: E402
from pokedex.config import settings  # noqa: E402
from pokedex.db import create_pool  # noqa: E402
from pokedex.wishlist.seed import SeedService  # noqa: E402


async def _sembrar() -> int:
    pool = create_pool()
    pool.open()
    pool.wait()
    async with httpx.AsyncClient(timeout=30) as client:
        catalog = CatalogService(TcgdexCatalog(settings.tcgdex_base_url, client), pool.connection)
        summary = await SeedService(catalog, pool.connection).sembrar()
    pool.close()
    print(
        f"Pokémon sembrados: {summary.pokemon}\n"
        f"Cartas por defecto espejadas: {summary.cartas_espejadas}\n"
        f"Cartas saltadas por catálogo inalcanzable: {summary.catalogo_inalcanzable}"
    )
    if summary.catalogo_inalcanzable > 0:
        print(
            "\nSiembra parcial: el catálogo (TCGdex) no respondió para "
            f"{summary.catalogo_inalcanzable} cartas. No se guardó nada a medias "
            "-- esas cartas se saltaron por completo. Vuelve a correr este mismo "
            "comando cuando el catálogo esté disponible para completarlas; lo ya "
            "espejado no se toca."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pokedex")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("sembrar", help="siembra los 151 Pokémon y espeja su carta por defecto")
    args = parser.parse_args(argv)
    if args.command == "sembrar":
        return asyncio.run(_sembrar())
    return 1


if __name__ == "__main__":
    sys.exit(main())
