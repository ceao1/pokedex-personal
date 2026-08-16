from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from pokedex.api.routes import catalog, pokedex
from pokedex.db import create_pool


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool = create_pool()
    pool.open()
    pool.wait()
    app.state.pool = pool
    app.state.http_client = httpx.AsyncClient(timeout=20)
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        pool.close()


app = FastAPI(title="Pokédex Viviente", lifespan=lifespan)
app.include_router(catalog.router)
app.include_router(pokedex.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
