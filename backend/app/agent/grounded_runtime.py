"""Buffered grounding adapter for W09. Provider/Hermes wiring stays separate."""
from collections.abc import Awaitable, Callable

from .contracts import ActionResult, ActionStarted, RunEnded, TextDelta
from .evidence import EvidencePackage
from .grounding import ValidatedReply, validate_answer
from .guard import LeakGuard
from .turn import Runtime


def grounded_runtime(package: EvidencePackage,
                     generate: Callable[[EvidencePackage], Awaitable[str | dict]],
                     guard: LeakGuard,
                     observe: Callable[[ValidatedReply], None] | None = None) -> Runtime:
    """Never expose raw generation. One model call, no repair/retry loop.

    Evidence must be built server-side by the caller using the authenticated owner
    profile. This is a reusable adapter, not a public chat route or Hermes adapter.
    Pass the SAME guard to run_turn so all emitted paths retain W09 checks.
    """
    async def events():
        yield ActionStarted(call_id="catalog", action="search_catalog")
        yield ActionResult(call_id="catalog", result={"success": package.status == "ok"})
        raw = await generate(package)
        reply = validate_answer(raw, package, guard)
        if observe:
            observe(reply)
        yield TextDelta(text=reply.text)
        yield RunEnded(status="completed")

    async def start():
        return events()

    return Runtime(start=start, duplicate_safe_start=False)
