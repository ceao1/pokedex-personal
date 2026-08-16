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


class AlreadyUploaded(Exception):
    """El objeto ya tiene bytes en el bucket -- no es un error del flujo.

    Verificado a mano contra Supabase Storage real: pedir una firma de
    subida para un path que ya tiene un objeto devuelve HTTP 400 con
    `{"statusCode":"409","error":"Duplicate"}`, y ni `x-upsert` en el PUT ni
    `{"upsert": true}` en la firma lo evitan -- el upsert queda fijo en el
    momento de firmar. Es justo lo que pasa si el celular ya subió la foto y
    reintenta `POST /captures` porque perdió la respuesta del primer intento.

    Se modela como una excepción propia (y no, por ejemplo, un `SignedUpload`
    con `token=""`) para que el servicio pueda distinguir "ya subido, no hay
    nada que firmar" de un error real sin inspeccionar el contenido de una
    URL -- y para que un error genuino (auth rechazada, bucket inexistente,
    red caída) siga propagándose tal cual, vía `raise_for_status()`.
    """


class StoragePort(Protocol):
    async def create_signed_upload(self, path: str) -> SignedUpload: ...

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str: ...

    async def signed_download_urls(
        self, paths: list[str], seconds: int = 3600
    ) -> dict[str, str | None]: ...


class SupabaseStorage:
    def __init__(
        self,
        base_url: str,
        secret_key: str,
        bucket: str,
        client: httpx.AsyncClient,
        public_base_url: str | None = None,
    ) -> None:
        # Dos bases a propósito. `_base` es la que usa el servidor para hablar
        # con Storage y vive en loopback. `_public_base` es la que se le
        # entrega al navegador: si el celular recibe una URL con 127.0.0.1
        # intenta subir a sí mismo, la conexión se rechaza y la foto se pierde
        # en silencio, porque el flujo está diseñado para guardar sin ella.
        self._base = f"{base_url.rstrip('/')}/storage/v1"
        self._public_base = f"{(public_base_url or base_url).rstrip('/')}/storage/v1"
        self._headers = {"Authorization": f"Bearer {secret_key}", "apikey": secret_key}
        self._bucket = bucket
        self._client = client

    async def create_signed_upload(self, path: str) -> SignedUpload:
        response = await self._client.post(
            f"{self._base}/object/upload/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={},
        )
        if response.status_code == 400:
            cuerpo = response.json()
            if cuerpo.get("statusCode") == "409" and cuerpo.get("error") == "Duplicate":
                raise AlreadyUploaded(path)
        response.raise_for_status()
        cuerpo = response.json()
        # La API devuelve la url con el token embebido en query string.
        url = cuerpo["url"]
        token = url.split("token=", 1)[1] if "token=" in url else cuerpo.get("token", "")
        return SignedUpload(
            path=path, signed_url=f"{self._public_base}/{url.lstrip('/')}", token=token
        )

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str:
        response = await self._client.post(
            f"{self._base}/object/sign/{self._bucket}/{path}",
            headers=self._headers,
            json={"expiresIn": seconds},
        )
        response.raise_for_status()
        return f"{self._public_base}/{response.json()['signedURL'].lstrip('/')}"

    async def signed_download_urls(
        self, paths: list[str], seconds: int = 3600
    ) -> dict[str, str | None]:
        """Firma varias descargas en una sola petición (el endpoint bulk de
        Storage), no una por ejemplar dentro de un bucle sin control -- una
        ficha con varios ejemplares no debe convertirse en N llamadas a red.

        Cada entrada de la respuesta puede traer su propio error (un objeto
        que ya no está en el bucket, por ejemplo) sin que eso tumbe a las
        demás: ese path queda en `None` y el resto sigue firmado.
        """
        if not paths:
            return {}
        response = await self._client.post(
            f"{self._base}/object/sign/{self._bucket}",
            headers=self._headers,
            json={"expiresIn": seconds, "paths": paths},
        )
        response.raise_for_status()
        firmadas: dict[str, str | None] = {}
        for entrada in response.json():
            path = entrada.get("path")
            if path is None:
                continue
            url = entrada.get("signedURL")
            firmadas[path] = f"{self._public_base}/{url.lstrip('/')}" if url else None
        return firmadas


class FakeStorage:
    """Doble de `StoragePort` para tests: no pega a la red.

    Registra las rutas pedidas para que un test pueda comprobar que el
    servicio armó el path esperado, sin depender de Supabase Storage real.

    `already_uploaded` deja que un test simule el 409 real: a diferencia de
    Supabase Storage, este fake no sabe si alguien hizo un PUT de verdad
    contra el path (esa subida ocurre directo celular-a-bucket, sin pasar
    por el backend), así que un test la marca a mano agregando el path acá
    antes de reintentar -- ver
    `test_post_captures_reintento_con_foto_ya_subida_no_revienta`.
    """

    def __init__(self) -> None:
        self.signed_uploads: list[str] = []
        self.signed_downloads: list[str] = []
        self.already_uploaded: set[str] = set()
        # Un test marca acá los paths que la firma en lote debe hacer fallar
        # (simula un objeto que ya no está en el bucket), sin tumbar el resto
        # del lote -- ver `signed_download_urls`.
        self.fallar_firma_de: set[str] = set()
        self.batch_calls: list[list[str]] = []

    async def create_signed_upload(self, path: str) -> SignedUpload:
        if path in self.already_uploaded:
            raise AlreadyUploaded(path)
        self.signed_uploads.append(path)
        return SignedUpload(
            path=path,
            signed_url=f"https://fake.storage.test/upload/{path}",
            token=f"fake-token-{path}",
        )

    async def signed_download_url(self, path: str, seconds: int = 3600) -> str:
        self.signed_downloads.append(path)
        return f"https://fake.storage.test/download/{path}?expires={seconds}"

    async def signed_download_urls(
        self, paths: list[str], seconds: int = 3600
    ) -> dict[str, str | None]:
        self.batch_calls.append(list(paths))
        self.signed_downloads.extend(paths)
        return {
            path: (
                None
                if path in self.fallar_firma_de
                else f"https://fake.storage.test/download/{path}?expires={seconds}"
            )
            for path in paths
        }
