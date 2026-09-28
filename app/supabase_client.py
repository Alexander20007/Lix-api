"""
Cliente Supabase via REST API (sem SDK, sem Rust).
"""

import os
import requests
from datetime import datetime, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
    raise RuntimeError(
        "Variaveis SUPABASE_URL e SUPABASE_SERVICE_KEY sao obrigatorias."
    )

BASE_URL = f"{SUPABASE_URL}/rest/v1"

HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}


def _parse_dt(value):
    """Converte string ISO do Supabase em datetime UTC-aware."""
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    # Se vier sem timezone (naive), assume UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ============ PROVIDERS ============

def get_provider_url(name: str) -> str:
    """Busca o dominio atual de um provedor ativo."""
    r = requests.get(
        f"{BASE_URL}/stream_providers",
        headers=HEADERS,
        params={
            "name": f"eq.{name}",
            "active": "eq.true",
            "select": "base_url",
            "limit": 1,
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        raise Exception(f"Provider '{name}' nao encontrado ou inativo")
    return data[0]["base_url"]


def list_providers() -> list:
    """Lista todos os provedores ativos."""
    r = requests.get(
        f"{BASE_URL}/stream_providers",
        headers=HEADERS,
        params={"active": "eq.true", "select": "name,base_url"},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def update_provider(name: str, new_url: str):
    """Atualiza o dominio de um provedor."""
    r = requests.patch(
        f"{BASE_URL}/stream_providers",
        headers=HEADERS,
        params={"name": f"eq.{name}"},
        json={
            "base_url": new_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


# ============ CACHE ============

def cache_get(key: str):
    """Retorna valor do cache se nao expirou, senao None."""
    r = requests.get(
        f"{BASE_URL}/stream_cache",
        headers=HEADERS,
        params={
            "cache_key": f"eq.{key}",
            "select": "payload,expires_at",
            "limit": 1,
        },
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    if not data:
        return None

    row = data[0]
    expires = _parse_dt(row["expires_at"])
    now = datetime.now(timezone.utc)

    if now >= expires:
        # Expirado: deleta e retorna None
        try:
            requests.delete(
                f"{BASE_URL}/stream_cache",
                headers=HEADERS,
                params={"cache_key": f"eq.{key}"},
                timeout=10,
            )
        except Exception:
            pass
        return None

    return row["payload"]


def cache_set(key: str, payload: dict, ttl_seconds: int = 600):
    """Salva no cache com TTL (upsert)."""
    expires = datetime.now(timezone.utc).timestamp() + ttl_seconds
    expires_iso = datetime.fromtimestamp(expires, tz=timezone.utc).isoformat()

    headers = HEADERS.copy()
    headers["Prefer"] = "resolution=merge-duplicates"

    r = requests.post(
        f"{BASE_URL}/stream_cache",
        headers=headers,
        json={
            "cache_key": key,
            "payload": payload,
            "expires_at": expires_iso,
        },
        timeout=10,
    )
    r.raise_for_status()


def cache_cleanup():
    """Remove entradas expiradas."""
    now_iso = datetime.now(timezone.utc).isoformat()
    r = requests.delete(
        f"{BASE_URL}/stream_cache",
        headers=HEADERS,
        params={"expires_at": f"lt.{now_iso}"},
        timeout=10,
    )
    r.raise_for_status()
