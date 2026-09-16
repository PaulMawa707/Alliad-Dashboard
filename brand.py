"""Customer branding and fleet scope for this deployment.

One dashboard instance serves one customer. Everything customer-specific that
appears on screen — or decides which VSS fleets and MiX sites belong to the
customer — is resolved here so a new deployment only needs new env values.
"""

from __future__ import annotations

import os

DEFAULT_BRAND = "Alliad"


def _env(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    return val.strip() if isinstance(val, str) else default


def brand_name() -> str:
    return _env("FLEET_BRAND_NAME") or DEFAULT_BRAND


def brand_tagline() -> str:
    return _env("FLEET_BRAND_TAGLINE") or "Fleet Health"


def brand_subtitle() -> str:
    """Small text next to the wordmark; lists the platforms in play."""
    explicit = _env("FLEET_BRAND_SUBTITLE")
    if explicit:
        return explicit
    sources = ["VSS", "MiX", "Track3"]
    return f"{brand_name()} · " + " · ".join(sources)


def page_title_suffix() -> str:
    return f"{brand_name()} {brand_tagline()}"


def vss_fleet_contains() -> str:
    """Keyword used to pick this customer's fleets out of the VSS fleet tree."""
    return _env("FLEET_VSS_CONTAINS") or brand_name()


def logo_file() -> str:
    """Full logo for light surfaces (the login card). Served from ``assets/``."""
    return _env("FLEET_LOGO_FILE") or "alliad_logo.svg"


def mark_file() -> str:
    """Logo mark for dark surfaces — the navy wordmark would vanish on the nav bar."""
    return _env("FLEET_MARK_FILE") or "alliad_mark.svg"


# The colour palette lives in assets/flask-theme.css (--nav-bg, --accent, and
# friends) and in components.BRAND_PRIMARY / BRAND_SECONDARY for charts.
