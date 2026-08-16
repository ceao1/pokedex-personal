import httpx


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
