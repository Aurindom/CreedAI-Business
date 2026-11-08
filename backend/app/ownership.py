"""Finds software an owner plainly says they already use, so the first lookup knows about it.

This runs before the model. It only reads the owner's own words, only recognises catalog
tools, and only accepts a plan name that the tool's sourced plan list contains.
"""

import re

from .schemas import Catalog, Tool

# "we use X", "we already pay for X", "I'm on X", "our team has X"
_OWNS_BEFORE = re.compile(r"\b(use|uses|using|used|have|has|pay for|paying for|run|runs|running|subscribe to|subscribed to|on)\b")
_OWNS_AFTER = re.compile(r"^(is what we use|is what i use|already)\b")
_NEGATION = re.compile(r"\b(dont|do not|doesnt|didnt|not|never|no longer|stopped|cancelled|canceled|quit|without|instead of|thinking about|considering|should i|looking at)\b")
_SPACES = re.compile(r"\s+")
_GENERIC_WORDS = {"online", "ai", "for", "restaurants", "pro", "profile", "business", "the"}


def _normalise(text: str) -> str:
    text = text.casefold().replace("'", "").replace("’", "")
    return _SPACES.sub(" ", re.sub(r"[^a-z0-9$]+", " ", text)).strip()


def _plan_names(tool: Tool) -> list[str]:
    tiers = tool.plan_tiers
    if tiers is None or tiers.status != "present" or not isinstance(tiers.value, list):
        return []
    return [str(name) for name in tiers.value if str(name).strip()]


def _names(tool: Tool, short_counts: dict[str, int]) -> list[str]:
    """The full catalog name, plus its first word when that word is distinctive and unique in the catalog."""
    full = _normalise(tool.name)
    names = [full]
    first = full.split(" ")[0]
    if first != full and len(first) >= 5 and first not in _GENERIC_WORDS and short_counts.get(first) == 1:
        names.append(first)
    return names


def _owned_at(before: str, after: str) -> bool:
    if _NEGATION.search(before):
        return False
    return bool(_OWNS_BEFORE.search(before) or _OWNS_AFTER.search(after))


def stated_ownership(catalog: Catalog, text: str) -> list[tuple[str, str | None]]:
    """Returns (tool_id, plan or None) for each catalog tool the owner says they already use."""
    said = _normalise(text)
    if not said:
        return []
    tools = [tool for tool in catalog.tools if tool.status != "rejected"]
    short_counts: dict[str, int] = {}
    for tool in tools:
        first = _normalise(tool.name).split(" ")[0]
        short_counts[first] = short_counts.get(first, 0) + 1

    found: list[tuple[str, str | None]] = []
    padded = f" {said} "
    for tool in tools:
        for name in sorted(_names(tool, short_counts), key=len, reverse=True):
            match = re.search(rf"(?<= ){re.escape(name)}(?= )", padded)
            if not match:
                continue
            before_words = padded[: match.start()].split()[-5:]
            after_text = padded[match.end():].strip()
            if not _owned_at(" ".join(before_words), after_text):
                break
            window = " ".join(padded[match.end():].split()[:4])
            plan = next(
                (plan for plan in _plan_names(tool) if re.search(rf"\b{re.escape(_normalise(plan))}\b", window)),
                None,
            )
            found.append((tool.id, plan))
            break
    return found
