"""Postgres connection URL (Neon, Supabase, or any compatible host)."""

from __future__ import annotations

import os


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    return val.strip() if isinstance(val, str) else ""


def postgres_url() -> str:
    """Return the dashboard Postgres URL.

    ``NEON_DB_URL`` is kept for backward compatibility (Vercel env name).
    ``DATABASE_URL`` / ``SUPABASE_DB_URL`` are also accepted.
    """
    for key in ("NEON_DB_URL", "DATABASE_URL", "SUPABASE_DB_URL"):
        val = _env(key)
        if val:
            return val
    return ""


def postgres_configured() -> bool:
    return bool(postgres_url())
