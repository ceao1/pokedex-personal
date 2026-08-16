import os
import subprocess

import pytest


def _supabase_status() -> dict[str, str]:
    """Lee la salida de `supabase status -o env` como diccionario."""
    result = subprocess.run(
        ["supabase", "status", "-o", "env"],
        capture_output=True,
        text=True,
        check=True,
        cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
    )
    values = {}
    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"')
    return values


@pytest.fixture(scope="session")
def supabase_env() -> dict[str, str]:
    return _supabase_status()


@pytest.fixture(scope="session")
def supabase_api_url(supabase_env: dict[str, str]) -> str:
    return supabase_env["API_URL"]


@pytest.fixture(scope="session")
def supabase_publishable_key(supabase_env: dict[str, str]) -> str:
    return supabase_env["PUBLISHABLE_KEY"]
