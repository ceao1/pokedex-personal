"""Comandos de línea de comandos.

uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx
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
from pokedex.wishlist.service import ImportService  # noqa: E402


async def _import_excel(path: str) -> int:
    pool = create_pool()
    pool.open()
    pool.wait()
    async with httpx.AsyncClient(timeout=30) as client:
        catalog = CatalogService(TcgdexCatalog(settings.tcgdex_base_url, client), pool.connection)
        summary = await ImportService(catalog, pool.connection).import_workbook(path)
    pool.close()
    print(
        f"Pokémon sembrados: {summary.pokemon}\n"
        f"Items creados: {summary.items_creados}\n"
        f"Items ya existentes: {summary.items_actualizados}\n"
        f"Opciones sin resolver: {summary.sin_resolver}\n"
        f"Opciones saltadas por catálogo inalcanzable: {summary.catalogo_inalcanzable}"
    )
    if summary.catalogo_inalcanzable > 0:
        print(
            "\nImport parcial: el catálogo (TCGdex) no respondió para "
            f"{summary.catalogo_inalcanzable} opciones. No se guardó nada a medias "
            "-- esas opciones se saltaron por completo. Vuelve a correr este mismo "
            "comando cuando el catálogo esté disponible para completarlas; lo ya "
            "resuelto no se toca."
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pokedex")
    sub = parser.add_subparsers(dest="command", required=True)
    importar = sub.add_parser("import-excel", help="siembra el checklist desde el Excel")
    importar.add_argument("path")
    args = parser.parse_args(argv)
    if args.command == "import-excel":
        return asyncio.run(_import_excel(args.path))
    return 1


if __name__ == "__main__":
    sys.exit(main())
