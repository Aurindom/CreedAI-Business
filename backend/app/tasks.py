import re

from .schemas import Catalog, ProblemCard, TaskMatch

_SUFFIXES = (("ies", "y"), ("s", ""), ("ing", ""), ("ed", ""), ("e", ""))
_CLAUSE_BREAK = re.compile(r"[.;!?\n]+|,?\s+\b(?:but|however|although|though|whereas|instead|except|yet)\b", re.IGNORECASE)
_NEGATION = re.compile(r"\b(?:not|no|never|without|dont|doesnt|didnt|isnt|arent|wont|cant)\b|n['’]t\b", re.IGNORECASE)
# These say the owner falls behind on a task, so they state the need instead of rejecting it.
_FALLING_BEHIND = re.compile(
    r"\b(?:never|rarely|do\s+not|don['’]?t|can\s*not|can['’]?t)\s+(?:"
    r"(?:get|got)\s+a?round\s+to"
    r"|(?:have|find)\s+(?:the\s+)?time\s+(?:to|for)"
    r"|keep\s+up(?:\s+with)?"
    # Not being reachable or not answering is the complaint itself ("customers can never reach us").
    r"|(?:\w+\s+)?(?:reach|contact|get\s+(?:through|hold\s+of))"
    # Phone answering only: "I never reply to reviews" is a deliberate refusal (see test_owner_phrases).
    r"|(?:\w+\s+)?(?:answer|pick\s+up|call\s+(?:\w+\s+)?back))\b"
    r"|\b(?:can|could)\s+never\s+(?:reach|contact|get\s+(?:through|hold\s+of))\b"
    r"|\bcould\s*n['’]?t\s+(?:reach|contact|get\s+(?:through|hold\s+of))\b", re.IGNORECASE)


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


def _negated(clause: str) -> bool:
    return bool(_NEGATION.search(_FALLING_BEHIND.sub(' ', clause)))


# An explicit "I don't need help with X" turns X down. Plain negation ("invoices don't get paid",
# "I don't want to answer calls myself") can still describe the problem, so it is not a rejection.
_REJECTION = re.compile(
    r"\b(?:do\s+not|don['’]?t|no\s+longer)\s+(?:really\s+)?need\b(?!\s+to\b)"
    r"|\b(?:do\s+not|don['’]?t)\s+want\s+(?:any\s+)?(?:help|a\s+tool|software)\b"
    r"|\bnot\s+(?:interested\s+in|looking\s+for)\b|\bno\s+need\s+for\b", re.IGNORECASE)


def _example_key(text: str) -> str:
    # Exact sentence identity, not a bag of words: wrappers and extra negation
    # must never acquire the authority of a server-owned example.
    return ' '.join(text.casefold().replace('\u2019', "'").split()).strip(' .!?')


def _example_cards(catalog: Catalog | None, text: str) -> list[ProblemCard]:
    key = _example_key(text)
    return [card for card in catalog.problem_cards if key and _example_key(card.plain_words) == key] if catalog else []


def affirmative_excerpt(text: str, excerpt: str, catalog: Catalog | None = None) -> bool:
    """Require an exact owner excerpt inside an affirmative clause, not a quote with negation removed."""
    normalize = lambda value: ' '.join(value.casefold().replace('\u2019', "'").split())
    wanted = normalize(excerpt)
    clauses = [part for clause in _CLAUSE_BREAK.split(text.replace('\u2019', "'"))
               for part in re.split(r'\b(?:so|therefore|as a result)\b', clause, flags=re.I)]
    return len(wanted) >= 1 and any(
        wanted in normalize(clause) and (bool(_example_cards(catalog, clause)) or not _negated(clause))
        for clause in clauses)


def owner_excerpts(text: str, catalog: Catalog | None = None) -> list[str]:
    """Offer exact source spans for structured routing, never catalog prose."""
    clauses = [part.strip() for clause in _CLAUSE_BREAK.split(text)
               for part in re.split(r'\b(?:so|therefore|as a result)\b', clause, flags=re.I)]
    coordinated = [part.strip() for clause in clauses if affirmative_excerpt(text, clause, catalog)
                   for part in re.split(r'\band\b', clause, flags=re.I)]
    return [part for part in dict.fromkeys([text, *clauses, *coordinated])
            if 1 <= len(part) <= 500 and affirmative_excerpt(text, part, catalog)]


def _stem(word: str) -> str:
    """Crude on purpose: it only has to make 'booking' meet 'book' and 'replies' meet 'reply'."""
    if word == 'getting':
        return 'get'
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


_PART_BREAK = re.compile(r",|\band\b", re.IGNORECASE)
# "went to a bar", "met at the restaurant": a place visited, not the owner's business.
_VISITED = re.compile(r"\b(?:to|at|from|near|in|into|by|outside)\s+(?:(?:a|an|the|this|that|some)\s+)?$", re.IGNORECASE)


def _label_pattern(label: str) -> re.Pattern[str]:
    words = r'[\s_-]+'.join(re.escape(word) for word in re.split(r'[\s_-]+', label.strip()) if word)
    return re.compile(r'(?<!\w)' + words + r'(?:e?s)?(?!\w)', re.IGNORECASE)


def _names_label(part: str, label: str) -> bool:
    return any(not _VISITED.search(part[:hit.start()]) for hit in _label_pattern(label).finditer(part))


def stated_trade(catalog: Catalog, text: str) -> str | None:
    """The one catalog business type the owner names, or None.

    Labels come only from the catalog (id, name, aliases), so new business types need no code.
    A miss only costs the old second Hermes run, while a wrong guess sticks because Hermes
    can't replace it unless the real business is named. So anything unclear returns None:
    negation, a place visited, a word inside a task phrase, or two different businesses.
    """
    found: set[str] = set()
    for clause in _CLAUSE_BREAK.split(_owner_text(text)):
        if not clause or not clause.strip():
            continue
        task_words = set().union(*(w for card in catalog.problem_cards for w in _phrase_hits(card, _words(clause))))
        named = [(part, {trade.id for trade in catalog.trades
                         if any(_names_label(part, label) and not _words(label) <= task_words
                                for label in [trade.id, trade.name, *trade.aliases])})
                 for part in _PART_BREAK.split(clause)]
        # "I don't have a bakery and restaurant": the negation reaches past "and".
        if any(ids and _negated(part) for part, ids in named):
            continue
        found.update(*(ids for part, ids in named if not _negated(part)))
    return next(iter(found)) if len(found) == 1 else None


def resolve_task(catalog: Catalog, text: str) -> TaskMatch:
    """Maps plain words to a known problem card using only the catalog's phrases.

    Phrases only count inside one clause. A negated clause ("I don't need...") can't give a
    confident match, and clauses pointing at different cards make the owner choose, because
    a bag of words can't tell "I answer calls fine but invoices are late" from a call problem.
    """
    stated: list[ProblemCard] = []
    negated: list[ProblemCard] = []
    only_rejections = True
    for clause in _CLAUSE_BREAK.split(_owner_text(text)):
        if clause and clause.strip():
            examples = _example_cards(catalog, clause)
            if examples:
                _add(stated, examples)
                continue
            hits = _clause_hits(catalog, _FALLING_BEHIND.sub(' ', clause))
            if _negated(clause):
                _add(negated, hits)
                only_rejections = only_rejections and (not hits or bool(_REJECTION.search(clause)))
            else:
                _add(stated, hits)
    choices = stated + [card for card in negated if card not in stated]
    if not choices:
        return TaskMatch(status="unsupported", message="We don't cover that task yet. Pick one of the listed problems instead.")
    # "I don't need help with calls, I need bookkeeping" names one need and turns the other down.
    # Matching it here saves Penny a second model run to re-route the turn.
    if len(stated) == 1 and negated and only_rejections:
        return TaskMatch(status="matched", problem_id=stated[0].id, choices=stated, message=f"Sounds like: {stated[0].title}.")
    if len(choices) == 1 and stated:
        return TaskMatch(status="matched", problem_id=choices[0].id, choices=choices, message=f"Sounds like: {choices[0].title}.")
    if len(choices) == 1:
        return TaskMatch(status="ambiguous", choices=choices, message=f"Did you mean: {choices[0].title}? Please confirm.")
    return TaskMatch(status="ambiguous", choices=choices, message="That could mean a few things. Which one is closest?")
