import re

from .schemas import Catalog, ProblemCard, TaskMatch

_SUFFIXES = (("ies", "y"), ("s", ""), ("ing", ""), ("ed", ""), ("e", ""))


def _stem(word: str) -> str:
    """Crude on purpose: it only has to make 'booking' meet 'book' and 'replies' meet 'reply'."""
    for suffix, swap in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + swap
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.casefold())}


def _score(card: ProblemCard, said: set[str]) -> int:
    """The longest phrase whose every word appears wins, so 'schedule jobs' beats a bare 'schedule'."""
    hits = [len(words) for words in (_words(p) for p in card.phrases) if words and words <= said]
    return max(hits, default=0)


def resolve_task(catalog: Catalog, text: str) -> TaskMatch:
    """Maps plain words to a known problem card using only the phrases in the catalog. A tie asks, nothing found says so."""
    said = _words(text)
    scored = [(card, _score(card, said)) for card in catalog.problem_cards]
    best = max((score for _, score in scored), default=0)
    if best == 0:
        return TaskMatch(status="unsupported", message="We don't cover that task yet. Pick one of the listed problems instead.")
    top = [card for card, score in scored if score == best]
    if len(top) == 1:
        return TaskMatch(status="matched", problem_id=top[0].id, choices=top, message=f"Sounds like: {top[0].title}.")
    return TaskMatch(status="ambiguous", choices=top, message="That could mean a few things. Which one is closest?")
