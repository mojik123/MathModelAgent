"""Core package bootstrap utilities.

This module is imported before submodules such as ``app.core.workflow``.  It
contains a narrow asyncio.gather patch for the question-group fan-out phase:
when all gathered awaitables are ``run_question_group_limited`` tasks, gather
returns exceptions as values so one failed question group does not cancel the
remaining running groups.
"""

from __future__ import annotations

import asyncio
from typing import Any


_ORIGINAL_GATHER = asyncio.gather
_PATCHED_ATTR = "_mathmodelagent_question_group_safe_gather"


def _is_question_group_task(awaitable: Any) -> bool:
    """Return True for workflow question-group tasks only.

    The patch intentionally targets the nested coroutine named
    ``run_question_group_limited`` in ``MathModelWorkFlow.execute``.  Other
    gather calls keep their original exception behavior.
    """
    try:
        coro = awaitable.get_coro() if hasattr(awaitable, "get_coro") else awaitable
        qualname = str(getattr(coro, "__qualname__", ""))
        return "run_question_group_limited" in qualname
    except Exception:
        return False


def _safe_gather(*aws: Any, **kwargs: Any):
    if (
        aws
        and "return_exceptions" not in kwargs
        and all(_is_question_group_task(aw) for aw in aws)
    ):
        kwargs["return_exceptions"] = True
    return _ORIGINAL_GATHER(*aws, **kwargs)


if not getattr(asyncio.gather, _PATCHED_ATTR, False):
    setattr(_safe_gather, _PATCHED_ATTR, True)
    asyncio.gather = _safe_gather  # type: ignore[assignment]
