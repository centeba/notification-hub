"""Optional fine-grained authorization hook.

In the SentinelBuild platform this called the central ``authz`` service to check
relationship tuples (e.g. "may agent X delegate on behalf of company Y?"). The
standalone notification-hub has no such service, so this ships a **permissive
default** (every check allowed) and a registration hook so a host that *does*
run an authorization service can wire it in:

    from integration_hub_backend._platform import authz

    async def my_checker(user, relation, obj, *, context=None,
                         fail_closed=True, **_):
        return await call_my_authz(user, relation, obj, context)

    authz.set_authz_checker(my_checker)

Until a checker is registered, ``authz_check`` logs a one-time warning and
returns ``True``. If you need deny-by-default behaviour standalone, register a
checker that returns ``False``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

logger = logging.getLogger(__name__)

AuthzChecker = Callable[..., Awaitable[bool]]

_checker: AuthzChecker | None = None
_warned = False


def set_authz_checker(checker: AuthzChecker | None) -> None:
    """Register (or clear) the host's authorization checker."""
    global _checker, _warned
    _checker = checker
    _warned = False


async def authz_check(
    user: str,
    relation: str,
    obj: str,
    *,
    context: dict[str, Any] | None = None,
    settings: Any | None = None,
    cache_ttl: float = 30.0,
    fail_closed: bool = True,
) -> bool:
    """Delegate to the registered checker, or allow by default.

    Signature mirrors the platform SDK's ``authz_check`` so call sites need no
    changes. When no checker is registered this returns ``True`` (permissive)
    after a one-time warning.
    """
    global _warned
    if _checker is None:
        if not _warned:
            logger.warning(
                "authz_check: no authorization checker registered — allowing all "
                "checks. Register one via _platform.authz.set_authz_checker to "
                "enforce delegation authorization."
            )
            _warned = True
        return True
    return await _checker(
        user,
        relation,
        obj,
        context=context,
        settings=settings,
        cache_ttl=cache_ttl,
        fail_closed=fail_closed,
    )
