"""Subida de fotos a Supabase Storage sin exponer la llave secreta.

El backend firma la subida y el navegador sube directo al bucket. Un
multipart desde el celular a través de FastAPI sería el cuello de botella
del flujo de 30 segundos.
"""

from typing import Protocol

import httpx
from pydantic import BaseModel


class SignedUpload(BaseModel):
    path: str
    signed_url: str
    token: str


class StoragePort(Protocol):
    async def create_signed_upload(self, path: str) -> SignedUpload: ...

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str: ...


class SupabaseStorage:
    def __init__(
        self, base_url: str, secret_key: str, bucket: str, client: httpx.AsyncClient
    ) -> None:
        self._base = f"{base_url.rstrip('/')}/storage/v1"
        self._headers = {"Authorization": f"Bearer {secret_key}", "apikey": secret_key}
        self._bucket = bucket
        self._client = client

    async def create_signed_upload(self, path: str) -> SignedUpload:
        response = await self._client.post(
            f"{self._base}/object/upload/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={},
        )
        response.raise_for_status()
        cuerpo = response.json()
        # La API devuelve la url con el token embebido en query string.
        url = cuerpo["url"]
        token = url.split("token=", 1)[1] if "token=" in url else cuerpo.get("token", "")
        return SignedUpload(path=path, signed_url=f"{self._base}/{url.lstrip('/')}", token=token)

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str:
        response = await self._client.post(
            f"{self._base}/object/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={"expiresIn": seconds},
        )
        response.raise_for_status()
        return f"{self._base}/{response.json()['signedURL'].lstrip('/')}"


class FakeStorage:
    """Doble de `StoragePort` para tests: no pega a la red.

    Registra las rutas pedidas para que un test pueda comprobar que el
    servicio armó el path esperado, sin depender de Supabase Storage real.

    Diverge a propósito de un detalle verificado a mano contra el Storage
    real: re-firmar la subida de un path que ya tiene objeto devuelve 409 ahí
    (ver `CaptureService.iniciar_captura`); acá siempre devuelve éxito. Un
    test de idempotencia contra este fake no puede probar esa arista -- solo
    prueba que el borrador no se duplica en la base.
    """

    def __init__(self) -> None:
        self.signed_uploads: list[str] = []
        self.signed_downloads: list[str] = []

    async def create_signed_upload(self, path: str) -> SignedUpload:
        self.signed_uploads.append(path)
        return SignedUpload(
            path=path,
            signed_url=f"https://fake.storage.test/upload/{path}",
            token=f"fake-token-{path}",
        )

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str:
        self.signed_downloads.append(path)
        return f"https://fake.storage.test/download/{path}?expires={seconds}"
