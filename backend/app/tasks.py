import re

from .schemas import Catalog, ProblemCard, TaskMatch

_SUFFIXES = (("ies", "y"), ("s", ""), ("ing", ""), ("ed", ""), ("e", ""))
_CLAUSE_BREAK = re.compile(r"[.;!?\n]+|,?\s+\b(?:but|however|although|though|whereas|instead|except|yet)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|no|never|without|dont|doesnt|didnt|isnt|arent|wont|cant)\b|n['’]t\b", re.IGNORECASE)


# Deliberately narrow spelling/slang aliases, not fuzzy matching of arbitrary words.
# Punctuation and negation remain in place for the existing clause safety rules.
_OWNER_WORDS = {
    'bookz': 'books', 'bookkeepin': 'bookkeeping', 'bookeeping': 'bookkeeping',
    'bookeping': 'bookkeeping', 'reciepts': 'receipts', 'expences': 'expenses',
    'invoicz': 'invoices', 'inovices': 'invoices', 'invoics': 'invoices',
    'paymnts': 'payments', 'reivews': 'reviews', 'reviewz': 'reviews',
    'replyin': 'reply', 'respondin': 'respond', 'ringin': 'rings', 'fone': 'phone',
    'schedual': 'schedule', 'scedule': 'schedule', 'schedul': 'schedule',
    'appt': 'appointments', 'appts': 'appointments', 'appointmnts': 'appointments',
    'custmers': 'customers', 'newsleter': 'newsletter', 'shiffts': 'shifts',
    'dispatchin': 'dispatch', 'tecs': 'technicians', 'r': 'are', 'aint': 'not',
}

def _owner_text(text: str) -> str:
    text = re.sub(r"\bbook\s+keeping\b", 'bookkeeping', text, flags=re.I)
    return re.sub(r"[a-z]+", lambda match: _OWNER_WORDS.get(match.group().casefold(), match.group()), text, flags=re.I)


def affirmative_excerpt(text: str, excerpt: str) -> bool:
    """Require an exact owner excerpt inside an affirmative clause, not a quote with negation removed."""
    normalize = lambda value: ' '.join(value.casefold().replace('\u2019', "'").split())
    wanted = normalize(excerpt)
    clauses = [part for clause in _CLAUSE_BREAK.split(text.replace('\u2019', "'"))
               for part in re.split(r'\b(?:so|therefore|as a result)\b', clause, flags=re.I)]
    return len(wanted) >= 1 and any(
        wanted in normalize(clause) and not _NEGATION.search(clause)
        for clause in clauses)


def owner_excerpts(text: str) -> list[str]:
    """Offer exact source spans for structured routing, never catalog prose."""
    clauses = [part.strip() for clause in _CLAUSE_BREAK.split(text)
               for part in re.split(r'\b(?:so|therefore|as a result)\b', clause, flags=re.I)]
    coordinated = [part.strip() for clause in clauses if affirmative_excerpt(text, clause)
                   for part in re.split(r'\band\b', clause, flags=re.I)]
    return [part for part in dict.fromkeys([text, *clauses, *coordinated])
            if 1 <= len(part) <= 500 and affirmative_excerpt(text, part)]


def _stem(word: str) -> str:
    """Crude on purpose: it only has to make 'booking' meet 'book' and 'replies' meet 'reply'."""
    for suffix, swap in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + swap
    return word


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", text.casefold())}


def _phrase_hits(card: ProblemCard, said: set[str]) -> list[set[str]]:
    return [words for words in (_words(p) for p in card.phrases) if words and words <= said]


def _clause_hits(catalog: Catalog, clause: str) -> list[ProblemCard]:
    """The longest phrase wins, so 'schedule jobs' beats a bare 'schedule'. A card matched on words
    the winning card doesn't explain is a separate need and is kept, so 'books' survives next to 'miss calls'."""
    said = _words(clause)
    hits = {card.id: _phrase_hits(card, said) for card in catalog.problem_cards}
    best = max((len(w) for found in hits.values() for w in found), default=0)
    if not best:
        return []
    winners = [card for card in catalog.problem_cards if any(len(w) == best for w in hits[card.id])]
    covered = set().union(*(w for card in winners for w in hits[card.id]))
    others = [card for card in catalog.problem_cards if card not in winners and any(not w <= covered for w in hits[card.id])]
    return winners + others


def _add(cards: list[ProblemCard], new: list[ProblemCard]) -> None:
    for card in new:
        if card not in cards:
            cards.append(card)


def resolve_task(catalog: Catalog, text: str) -> TaskMatch:
    """Maps plain words to a known problem card using only the catalog's phrases.

    Phrases only count inside one clause. A negated clause ("I don't need...") can't give a
    confident match, and clauses pointing at different cards make the owner choose, because
    a bag of words can't tell "I answer calls fine but invoices are late" from a call problem.
    """
    stated: list[ProblemCard] = []
    negated: list[ProblemCard] = []
    for clause in _CLAUSE_BREAK.split(_owner_text(text)):
        if clause and clause.strip():
            _add(negated if _NEGATION.search(clause) else stated, _clause_hits(catalog, clause))
    choices = stated + [card for card in negated if card not in stated]
    if not choices:
        return TaskMatch(status="unsupported", message="We don't cover that task yet. Pick one of the listed problems instead.")
    if len(choices) == 1 and stated:
        return TaskMatch(status="matched", problem_id=choices[0].id, choices=choices, message=f"Sounds like: {choices[0].title}.")
    if len(choices) == 1:
        return TaskMatch(status="ambiguous", choices=choices, message=f"Did you mean: {choices[0].title}? Please confirm.")
    return TaskMatch(status="ambiguous", choices=choices, message="That could mean a few things. Which one is closest?")
