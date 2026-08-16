import tomllib
from pathlib import Path

import httpx

_CONFIG_TOML = Path(__file__).parent / ".." / ".." / "supabase" / "config.toml"


# Prueba de extremo a extremo: confirma que el endpoint es inalcanzable hoy,
# pero no distingue *por qué* — un 401 por el revoke de la Task 2 y un 401
# por cualquier otra capa (o incluso el 404 de "la tabla no está en un
# esquema expuesto") pasan igual esta aserción. Ver el test de abajo, que
# vigila la causa concreta que este test no puede aislar.
def test_data_api_no_expone_el_esquema_app(supabase_api_url: str, supabase_publishable_key: str):
    """La colección entera queda legible desde el navegador si app se expone."""
    response = httpx.get(
        f"{supabase_api_url}/rest/v1/card",
        params={"select": "*"},
        headers={
            "apikey": supabase_publishable_key,
            "Authorization": f"Bearer {supabase_publishable_key}",
        },
    )
    assert response.status_code >= 400, (
        f"app.card es alcanzable por la Data API: {response.status_code} {response.text}"
    )


def test_app_no_esta_en_los_esquemas_expuestos_de_config_toml():
    """`app` no debe aparecer nunca en `[api].schemas` de `supabase/config.toml`.

    Ese archivo es la única fuente de verdad sobre qué esquemas sirve la Data
    API. Si alguien agrega `app` a esa lista, la llave publicable que viaja
    en el bundle del navegador queda a un paso de leer toda la colección
    (el test HTTP de arriba no lo notaría si, además, el `revoke` de la
    Task 2 sigue vigente).
    """
    with _CONFIG_TOML.open("rb") as f:
        config = tomllib.load(f)

    schemas = config["api"]["schemas"]

    assert schemas, (
        "[api].schemas está vacío o ausente en supabase/config.toml: "
        "no se puede verificar que app siga sin exponerse"
    )
    assert "public" in schemas, (
        f"[api].schemas no contiene 'public' ({schemas}): la clave puede "
        "haberse movido o renombrado, y esta prueba ya no está mirando lo "
        "que cree que mira"
    )
    assert "app" not in schemas, (
        f"'app' está en [api].schemas de supabase/config.toml ({schemas}): "
        "toda la colección quedaría detrás de la llave publicable que "
        "viaja en el bundle del navegador"
    )
