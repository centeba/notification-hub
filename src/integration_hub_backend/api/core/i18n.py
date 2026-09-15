"""Local i18n loader for notification-hub-owned translation namespaces.

Translation files live *inside this package* at::

    integration_hub_backend/i18n/{locale}/{namespace}.json

This loader reads them directly from disk with an in-process cache — no HTTP
call, no Redis dependency, no coupling to the multi-lang service.

For **shared** namespaces (e.g. ``app`` — the User Master strings served by
the standalone multi-lang service), use ``MultiLangClient`` instead.

Supported locales at launch: en-US, es-ES, fr-FR.  Unknown locales fall back
to ``en-US`` automatically.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Root directory for bundled i18n files, relative to this module.
#:   <pkg_root>/api/core/i18n.py  →  up 3 levels  →  <pkg_root>/
#:   then down into i18n/
_I18N_DIR: Path = Path(__file__).parent.parent.parent / "i18n"

_FALLBACK_LOCALE = "en-US"

# Canonical locale codes this package ships translations for.
_SUPPORTED_LOCALES: frozenset[str] = frozenset({"en-US", "es-ES", "fr-FR"})

# Accepts short codes ("en", "fr") and underscore variants ("en_US") and maps
# them to canonical BCP-47 tags shipped with the package.
_LOCALE_ALIASES: dict[str, str] = {
    "en": "en-US",
    "en-us": "en-US",
    "en_us": "en-US",
    "en_US": "en-US",
    "es": "es-ES",
    "es-es": "es-ES",
    "es_es": "es-ES",
    "es_ES": "es-ES",
    "fr": "fr-FR",
    "fr-fr": "fr-FR",
    "fr_fr": "fr-FR",
    "fr_FR": "fr-FR",
}

# ---------------------------------------------------------------------------
# In-process cache (intentionally per-pod, no Redis)
# ---------------------------------------------------------------------------
# This is a memoize over immutable JSON files baked into the Docker image
# at ``integration_hub_backend/i18n/{locale}/{namespace}.json``. The data
# is identical on every replica (same image, same files) so a Redis-shared
# cache would add a network round-trip for zero consistency benefit.
#
# Audited as part of Phase 1.3 of the architecture assessment (move
# stateful caches to Redis or annotate as per-pod-immutable). This one
# is correctly per-pod — leave it.
#
# If a future change makes the translation source mutable at runtime
# (e.g. admin-edited locale strings), promote this to Redis with a
# pub/sub invalidation channel.

_cache: dict[str, dict[str, Any]] = {}
_cache_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize_locale(locale: str) -> str:
    """Map any locale variant to a canonical code, falling back to en-US."""
    return _LOCALE_ALIASES.get(locale, _LOCALE_ALIASES.get(locale.lower(), _FALLBACK_LOCALE))


def _load(locale: str, namespace: str) -> dict[str, Any]:
    """Load *namespace* translations for *locale* from disk (cached)."""
    cache_key = f"{locale}:{namespace}"

    with _cache_lock:
        if cache_key in _cache:
            return _cache[cache_key]

    path = _I18N_DIR / locale / f"{namespace}.json"

    if not path.is_file():
        if locale != _FALLBACK_LOCALE:
            log.warning(
                "i18n_locale_missing",
                namespace=namespace,
                locale=locale,
                fallback=_FALLBACK_LOCALE,
            )
            data = _load(_FALLBACK_LOCALE, namespace)
        else:
            log.error("i18n_file_missing", path=str(path))
            data = {}
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("i18n_parse_error", path=str(path), error=str(exc))
            data = {}

    with _cache_lock:
        _cache[cache_key] = data

    return data


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_translations(namespace: str, locale: str = "en-US") -> dict[str, Any]:
    """Return the translation dict for *namespace* and *locale*.

    Reads from ``integration_hub_backend/i18n/{locale}/{namespace}.json``.
    Falls back to ``en-US`` if the requested locale is unavailable.
    Returns an empty dict (never raises) if the file cannot be read.

    Use this function for namespaces owned by this project (e.g.
    ``"notification_hub"``).  For shared namespaces served by the standalone
    multi-lang service (e.g. ``"app"``), use
    ``integration_hub_backend.api.integrations.multi_lang_client.MultiLangClient``.

    Example::

        strings = get_translations("notification_hub", locale="es-ES")
        title = strings.get("dashboard", {}).get("title", "Dashboard")
    """
    canonical = _normalize_locale(locale)
    return _load(canonical, namespace)


def get_string(namespace: str, *key_path: str, locale: str = "en-US") -> str:
    """Convenience helper — walks *key_path* inside the namespace dict.

    Returns the last segment of *key_path* as a raw string if the key is not
    found (so UIs degrade gracefully to the key name rather than crashing).

    Example::

        label = get_string("notification_hub", "rules", "new_rule", locale="fr-FR")
        # → "Nouvelle règle"
    """
    data: Any = get_translations(namespace, locale)
    for key in key_path:
        if not isinstance(data, dict):
            return key_path[-1]
        data = data.get(key)
        if data is None:
            return key_path[-1]
    return data if isinstance(data, str) else key_path[-1]
