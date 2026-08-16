"""Comandos de línea de comandos.

uv run python -m pokedex.cli import-excel ../Pokedex_Viviente_151.xlsx
"""

import argparse
import asyncio
import sys

import httpx

from pokedex.catalog.service import CatalogService
from pokedex.catalog.tcgdex import TcgdexCatalog
from pokedex.config import settings
from pokedex.db import create_pool
from pokedex.wishlist.service import ImportService


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
        f"Opciones sin resolver: {summary.sin_resolver}"
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
