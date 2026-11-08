"""Validate semantic routing proposals before rebuilding factual evidence.

Routing identifies owner intent. It cannot supply product facts or skip public reads.
"""
import re

from pydantic import Field

from .agent.evidence import Strict, build_evidence
from .penny_grounding import filtered_context, qualify_package, selected_task_ids


class Task(Strict):
    problem_id: str
    task_text: str = Field(min_length=1, max_length=500)


class Routing(Strict):
    routes: list[Task] | None = Field(default=None, max_length=3)
    trade: str | None = None
    trade_text: str | None = Field(default=None, max_length=300)


def apply(raw, catalog, profile, memory, body):
    proposal = Routing.model_validate({key: raw.get(key) for key in ('routes', 'trade', 'trade_text')})
    tasks = []
    for route in proposal.routes or []:
        tasks += selected_task_ids(catalog, body, route.model_dump())
    tasks = list(dict.fromkeys(tasks))
    updated = profile
    if proposal.trade is not None and catalog.resolve_trade(proposal.trade) != profile.trade:
        trade = catalog.resolve_trade(proposal.trade)
        excerpt = proposal.trade_text or ''
        # The current owner must explicitly name this business. History cannot
        # silently overwrite a correction. Never infer a trade from a product.
        names = [trade] if trade else []
        names += [entry.name for entry in catalog.trades if entry.id == trade]
        aliases = [name.replace('_', ' ') for name in names]
        if (not trade or not excerpt or excerpt.casefold() not in body.message.casefold()
                or not any(re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)', excerpt, re.I) for name in aliases)
                or re.search(r"\b(?:not|never|no)\b|n't\b", excerpt, re.I)):
            raise ValueError('unbound_business_context')
        updated = profile.model_copy(update={'trade': trade})
    if not tasks:
        return None
    clean, updated = filtered_context(catalog, updated, memory)
    package = qualify_package(clean, build_evidence(clean, updated, tasks), body)
    return package, updated, tasks
