"""Core package bootstrap utilities."""

from __future__ import annotations

import asyncio
from typing import Any


_ORIGINAL_WAIT_FOR = asyncio.wait_for
_PATCHED_WAIT_FOR_ATTR = "_mathmodelagent_nonpositive_timeout_is_none"


async def _safe_wait_for(awaitable: Any, timeout: float | None = None, *args: Any, **kwargs: Any):
    """Treat timeout<=0 as no timeout.

    Workflow settings use 0 to mean that a stage should not be stopped by a
    total-duration budget. Native asyncio.wait_for(timeout=0) cancels
    immediately, so this adapter preserves the intended workflow semantics.
    """
    if timeout is not None and timeout <= 0:
        timeout = None
    return await _ORIGINAL_WAIT_FOR(awaitable, timeout=timeout, *args, **kwargs)


if not getattr(asyncio.wait_for, _PATCHED_WAIT_FOR_ATTR, False):
    setattr(_safe_wait_for, _PATCHED_WAIT_FOR_ATTR, True)
    asyncio.wait_for = _safe_wait_for  # type: ignore[assignment]
