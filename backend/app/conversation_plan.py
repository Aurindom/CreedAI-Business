"""Versioned semantic response plans. Plans propose operations, never account/vendor facts.

Fast recognition is an optimization for completely understood utterances only.
An unrecognized clause sends the entire request to Hermes, not a partial reply.
"""
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Step(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['recall', 'forget', 'favourites_list', 'favourites_save', 'favourites_remove',
                  'help', 'compare', 'clarify', 'scope', 'social', 'recommend']
    owner_text: str = Field(min_length=1, max_length=500)
    topic: Literal['overview', 'businesses', 'favourites', 'history', 'comparison', 'account',
                   'acquisition', 'workflow', 'greeting', 'thanks', 'wellbeing'] | None = None
    criterion: Literal['price', 'plan', 'cost', 'fit'] | None = None
    presentation: Literal['table', 'list', 'prose'] | None = None
    tool_ids: list[str] = Field(default_factory=list, max_length=6)
    exclude_tool_ids: list[str] = Field(default_factory=list, max_length=20)
    problem_ids: list[str] = Field(default_factory=list, max_length=3)
    context_mode: Literal['owner', 'scenario'] = 'owner'
    assumed_business: str | None = Field(default=None, max_length=100)


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    steps: list[Step] = Field(min_length=1, max_length=6)


def strict_schema():
    """OpenRouter strict schemas require every property, including nullable/default fields."""
    schema = Plan.model_json_schema()
    def strict(value):
        if isinstance(value, dict):
            value.pop('default', None)
            value.pop('title', None)
            if value.get('type') == 'object':
                value['additionalProperties'] = False
                value['required'] = list(value.get('properties', {}))
            for child in value.values():
                strict(child)
        elif isinstance(value, list):
            for child in value:
                strict(child)
    strict(schema)
    # Embed without external definitions, so the gateway can add it to its schema.
    step = schema.pop('$defs')['Step']
    schema['properties']['steps']['items'] = step
    return schema


def contextual_language(text):
    """Do not treat examples, quotations, third parties or conditionals as owner assertions."""
    return bool(re.search(r'\b(?:imagine|imagining|suppose|supposing|hypothetically|hypothetical|'
                          r'pretend|assuming|assume|what if|if i|if we|my competitor|their business|'
                          r'a friend|my friend|someone|he says|she says|they said)\b|["“”]', text, re.I))


def goal_from_text(text):
    if contextual_language(text):
        return None
    goal = re.search(r'\b(?:i|we)\s+(?:need|want)\s+(?:help\s+)?(?:with\s+|to\s+)?([^.!?]+)|\bhow (?:do|can|could) (?:i|we)\s+([^.!?]+)', text, re.I)
    return next(value for value in goal.groups() if value)[:300] if goal else None


def mentioned_tools(catalog, text):
    return [tool.id for tool in catalog.tools if tool.status != 'rejected' and any(
        re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I)
        for name in (tool.id.replace('_', ' '), tool.name))]


def fast_task_covered(catalog, body):
    """Every independent clause must be a known task or explicit owner context.

    A keyword hit in one clause is insufficient authority to consume the rest
    of a compound request. Uncovered text is interpreted once by Hermes.
    """
    from .conversation_state import business_description
    from .ownership import stated_ownership
    from .tasks import resolve_task
    normalize = lambda value: ' '.join(value.casefold().split()).strip(' .!?')
    if any(normalize(body.message) in (normalize(card.plain_words), normalize(card.title)) for card in catalog.problem_cards):
        return True  # Exact app-owned task examples or a tapped card title, not arbitrary substring hits.
    if contextual_language(body.message):
        return False
    parts = [part.strip() for part in re.split(r'[.!?;,\n]+|\band\b', body.message, flags=re.I) if part.strip()]
    for part in parts:
        if re.search(r'\b(?:favourites?|favorites?|bookmarks?|remember|forget|website|history|exclude|remove|table)\b', part, re.I):
            return False
        if (resolve_task(catalog, part).status != 'matched' and not business_description(part)
                and not stated_ownership(catalog, part)):
            return False
    return bool(parts)


def comparison_tools(catalog, text):
    """Keep positive selections and negative constraints separate, including list conjunctions."""
    positive, excluded = [], []
    for clause in re.split(r'[.;!?]|\bbut\b', text, flags=re.I):
        neg = re.search(r"\b(?:exclude|excluding|except|without|omit|remove|leave out|do not list|don't list|not including)\b", clause, re.I)
        if neg:
            excluded += mentioned_tools(catalog, clause[neg.end():])
            positive += mentioned_tools(catalog, clause[:neg.start()])
        else:
            positive += mentioned_tools(catalog, clause)
    return list(dict.fromkeys(positive)), list(dict.fromkeys(excluded))


_LEAD_IN = re.compile(r"^(?:(?:so|and|also|ok|okay|hey|well|then|arkadio|btw|by the way|quick question)[, ]+)+")
_TRAIL = re.compile(r"(?:[, ]+(?:yet|so far|right now|currently|again|please|now|then|already|at all|at the moment|by the way))+$")
_BUSINESS = r"(?:business|business type|type of business|kind of business|line of business|shop|company)"
_ASK = r"(?:do you (?:not )?|don't you |can you |could you |did you |please )?(?:remember|recall|know|tell me|remind me)"
_SAVED = r"(?:(?:saved |bookmarked |fav(?:ourite|orite)? )+(?:tools?|ones|list)|fav(?:ourite|orite)?s|favs|bookmarks)"
_MINE = r"(?:my |our )"
_OWN_BUSINESS = tuple(re.compile(pattern) for pattern in (
    rf"{_ASK}(?: what| which)? (?:my |our |the )?{_BUSINESS}(?: is| was)?",
    rf"{_ASK} (?:what|which) (?:kind of |type of |sort of )?{_BUSINESS} (?:i|we) (?:have|run|own|operate|do)",
    rf"{_ASK} what (?:i|we) (?:run|own|do for (?:a living|work))",
    rf"(?:what|which) (?:kind of |type of |sort of )?{_BUSINESS} (?:do|did) (?:i|we) (?:have|run|own|operate|do)",
    rf"(?:what|which) (?:kind of |type of |sort of )?{_BUSINESS} (?:am i|are we) (?:in|running)",
    rf"what(?:'s| is| was) (?:my|our) {_BUSINESS}",
    rf"what did (?:i|we) (?:tell you|say) (?:about )?(?:my|our) {_BUSINESS}(?: is| was)?",
    rf"what (?:do|did) you (?:know|remember|have) about (?:my|our) {_BUSINESS}",
    rf"what {_BUSINESS} did (?:i|we) (?:tell you|say|mention)(?: (?:i|we) (?:have|run|own))?",
))
_OWN_FAVOURITES = tuple(re.compile(pattern) for pattern in (
    rf"(?:what|which) (?:are|is|were) (?:in |on )?{_MINE}?{_SAVED}",
    rf"what(?:'s| is| do i have| have i got) (?:in|on|saved in|saved to) {_MINE}{_SAVED}",
    rf"(?:(?:can|could|would) you )?(?:show|list|tell|give|read)(?: me)? (?:all )?(?:of )?{_MINE}{_SAVED}",
    rf"(?:do|did|have) (?:i|we) (?:have |got |saved? |bookmark(?:ed)? )?(?:any|some) {_SAVED}",
    rf"(?:do|did|have) (?:i|we) (?:saved?|bookmark(?:ed)?|added|add) (?:any|some|anything|any tools?|some tools?)(?: (?:as|to|in|on) {_MINE}?{_SAVED})?",
    rf"(?:are|is) there (?:any|anything|any tools?|some tools?)(?: saved)? (?:in|on|as) {_MINE}{_SAVED}",
    rf"any {_SAVED}",
    rf"anything (?:in|on) {_MINE}{_SAVED}",
    rf"how many (?:{_SAVED}|tools) (?:do|have|did) (?:i|we)(?: have| got| saved?| bookmark(?:ed)?)?(?: (?:as|to|in|on) {_MINE}?{_SAVED})?",
    rf"(?:what|which) tools (?:are|do i have) (?:in|on|saved in|saved as) {_MINE}?{_SAVED}",
))


def _core(clause):
    """The question itself, without conversational lead-ins and trailing fillers."""
    text = ' '.join(clause.casefold().replace('\u2019', "'").split())
    return _TRAIL.sub('', _LEAD_IN.sub('', text)).strip(' ,')


def asks_own_business(clause):
    """A question about the business this owner already gave, in any common wording."""
    return not contextual_language(clause) and any(pattern.fullmatch(_core(clause)) for pattern in _OWN_BUSINESS)


def asks_own_favourites(clause):
    """A question about what is on the owner's own list. Never a how-to, a write or a hypothetical."""
    return not contextual_language(clause) and any(pattern.fullmatch(_core(clause)) for pattern in _OWN_FAVOURITES)


def restates_business(clause, memory):
    """'Remember I have a coffee shop' restates the business already held for this conversation."""
    from .conversation_state import business_description
    if contextual_language(clause) or not memory.business_description:
        return False
    stated = re.fullmatch(r"\s*(?:(?:do|can|could|will) you |please |you )?(?:remember|recall|note|keep in mind)(?: that)? (.+)", clause, re.I)
    described = business_description(stated.group(1)) if stated else None
    return bool(described) and described.casefold() == memory.business_description.casefold()


READ_ONLY_KINDS = ('recall', 'favourites_list', 'help')


def local_plan(message, memory, catalog):
    """Only a fully covered request can bypass semantic planning.

    These rules never classify an arbitrary business question as app help just
    because it contains 'help', 'business', 'saved' or a vendor name.
    """
    steps, missed = _clause_steps(message, memory, catalog)
    return Plan(steps=steps) if steps and not missed else None


def known_parts(message, memory, catalog):
    """Read-only steps the app can answer by itself when the model cannot run, plus the rest.

    Writes, comparisons and anything unrecognised stay in the second list, so a
    degraded turn never changes account data or guesses at a business question."""
    steps, missed = _clause_steps(message, memory, catalog)
    safe = [step for step in steps if step.kind in READ_ONLY_KINDS]
    rest = [step.owner_text for step in steps if step.kind not in READ_ONLY_KINDS] + missed
    return (Plan(steps=safe), rest) if safe and rest else (None, rest)


def _clause_steps(message, memory, catalog):
    from .conversation_state import criterion_for
    clauses = [part.strip(' ,.!?') for part in re.split(r'[?;\n]+|\.(?:\s+|$)|\s+and\s+(?=(?:what|how|do you|can you|show|list|forget|remove)\b)', message, flags=re.I) if part.strip(' ,.!?')]
    if not clauses or len(clauses) > 6:
        return [], clauses
    steps, missed = [], []
    for clause in clauses:
        text = clause.casefold().strip()
        criterion_answer = bool(criterion_for(clause) and re.fullmatch(r'(?:by |the |on |required |overall |total |added |monthly |lowest |cheapest |their |price|prices|pricing|cost|plans?|tiers?|features?|fit|suitability|and|\s)+', text))
        fav = re.search(r'\b(?:fav(?:ourite|orite)?s?|bookmarks?|saved tools)\b', text)
        kind = topic = None
        ids = mentioned_tools(catalog, clause)
        if memory.pending_favourite_action and memory.pending_favourite_ids and text in ('yes', 'yes please', 'confirm', 'please do'):
            kind = 'favourites_' + memory.pending_favourite_action
            ids = memory.pending_favourite_ids[:]
        elif memory.pending_favourite_action and ids and all(
                re.fullmatch(re.escape(tool.name.casefold()), text) or re.fullmatch(re.escape(tool.id.replace('_', ' ')), text)
                for tool in catalog.tools if tool.id in ids):
            kind = 'favourites_' + memory.pending_favourite_action
        elif re.fullmatch(r"(?:please )?(?:forget|clear|erase|stop remembering|do not remember|don't remember) (?:my |our |the )?(?:business|business context|business type|shop)(?: please)?", text):
            kind = 'forget'
        elif re.fullmatch(r"(?:do you (?:not )?|can you |please )?(?:remember|recall)(?: what)? (?:my |our |the )?(?:business|business type|shop)(?: is)?", text):
            kind = 'recall'
        elif asks_own_business(clause) or restates_business(clause, memory):
            kind = 'recall'
        elif asks_own_favourites(clause):
            kind = 'favourites_list'
        elif fav:
            if re.match(r'(?:how|where|can i)\b', text):
                kind, topic = 'help', 'favourites'
            elif re.fullmatch(r"(?:(?:what|which) are )?(?:my |our |the |saved )?(?:fav(?:ourite|orite)?s?|bookmarks?)(?: tools?)?", text) or re.fullmatch(r'(?:show|list)(?: me)? (?:my |our )?(?:saved |favourite |favorite )*tools', text):
                kind = 'favourites_list'
            elif re.fullmatch(r'(?:what|which) tools (?:have i |did i )?(?:saved|bookmarked)(?: as| to| in)? (?:my )?(?:favourites|favorites|fav tools)', text):
                kind = 'favourites_list'
            elif explicit_write(clause, 'favourites_remove'):
                kind = 'favourites_remove'
            elif explicit_write(clause, 'favourites_save'):
                kind = 'favourites_save'
        elif re.fullmatch(r'(?:what is|tell me about|explain) (?:this|the) (?:website|app|platform|site)(?: about| for)?|what (?:can|do) you do(?: for me)?', text):
            kind, topic = 'help', 'overview'
        elif re.fullmatch(r'(?:how|where|can i)\b.{0,90}\b(?:history|conversations|past chats)\b.{0,25}', text):
            kind, topic = 'help', 'history'
        elif re.fullmatch(r'(?:hi|hello|hey)(?: there| again)?', text):
            kind, topic = 'social', 'greeting'
        elif re.fullmatch(r'how (?:are|r) (?:you|u)(?: doing)?', text):
            kind, topic = 'social', 'wellbeing'
        elif re.fullmatch(r'(?:thanks|thank you)(?: very much| so much| a lot)?', text):
            kind, topic = 'social', 'thanks'
        elif not re.search(r"\b(?:don't|do not|never)\s+compare\b", text) and (
            re.fullmatch(r'(?:please |can you |could you )?(?:compare|show|give|make|put|format|present)\b.{0,150}', text)
            and re.search(r'\b(?:compar\w*|versus|vs|table|prices?|plans?|costs?|options|alternatives)\b', text)
            or criterion_answer and (memory.last_tool_ids or memory.pending_question == 'comparison')):
            if not re.search(r'\b(?:favourite|favorite|history|business)\b', text):
                kind = 'compare'
        if kind is None:
            missed.append(clause)
            continue
        positive, excluded = comparison_tools(catalog, clause) if kind == 'compare' else (ids, [])
        steps.append(Step(kind=kind, owner_text=clause, topic=topic, tool_ids=positive,
                          exclude_tool_ids=excluded, criterion=criterion_for(clause) if kind == 'compare' else None,
                          presentation='table' if kind == 'compare' and re.search(r'\btable\b', text) else None))
    return steps, missed


def explicit_write(text, kind):
    """An imperative/direct request is required; a how-to, quote or bookmark assertion isn't a write."""
    if contextual_language(text) or re.search(r'\b(?:how|where|should i|could i|can i|do not|don\x27t|never)\b', text, re.I):
        return False
    verb = r'(?:remove|delete|unsave|unbookmark)' if kind == 'favourites_remove' else r'(?:save|add|bookmark|favourite|favorite)'
    return bool(re.match(rf'\s*(?:please\s+)?(?:(?:can|could|would|will) you\s+)?(?:please\s+)?{verb}\b', text, re.I))


def bound_write_ids(step, body, catalog, memory):
    """Resolve explicit names or a single/ordinal contextual reference; never accept model identity."""
    named = mentioned_tools(catalog, step.owner_text)
    if (memory.pending_favourite_action == step.kind.removeprefix('favourites_') and memory.pending_favourite_ids
            and step.owner_text.casefold().strip(' .!?') in ('yes', 'yes please', 'confirm', 'please do')):
        return memory.pending_favourite_ids[:]
    answering = (memory.pending_favourite_action == step.kind.removeprefix('favourites_') and len(named) == 1
                 and any(step.owner_text.casefold() == value.casefold() for tool in catalog.tools if tool.id == named[0]
                         for value in (tool.name, tool.id.replace('_', ' '))))
    if not explicit_write(step.owner_text, step.kind) and not answering:
        return []
    ids = named
    if not ids:
        ordinal = re.search(r'\b(first|second|third|fourth|fifth|sixth)\b', step.owner_text, re.I)
        if ordinal:
            index = ['first', 'second', 'third', 'fourth', 'fifth', 'sixth'].index(ordinal.group().lower())
            ids = memory.last_tool_ids[index:index + 1]
        elif re.search(r'\b(?:it|that|this)(?: tool| one)?\b', step.owner_text, re.I) and len(memory.last_tool_ids) == 1:
            ids = memory.last_tool_ids[:]
    # Explicitly named tools must match, even if the model proposed a different tool.
    return ids if ids and (not step.tool_ids or set(ids) == set(step.tool_ids)) else []


def validate_plan(raw, body, catalog):
    plan = Plan.model_validate(raw)
    known = {tool.id for tool in catalog.tools if tool.status != 'rejected'}
    problems = {card.id for card in catalog.problem_cards}
    for step in plan.steps:
        if step.owner_text.casefold() not in body.message.casefold():
            raise ValueError('unbound_conversation_action')
        if not set(step.tool_ids + step.exclude_tool_ids) <= known or not set(step.problem_ids) <= problems:
            raise ValueError('unbound_conversation_action')
        if step.kind == 'forget' and not re.search(r"\b(?:forget|erase|clear|stop remembering|do not remember|don't remember)\b", step.owner_text, re.I):
            raise ValueError('unbound_conversation_action')
        if step.kind == 'forget' and (contextual_language(step.owner_text) or re.search(r"\b(?:do not forget|don't forget|never forget|not asking.*forget)\b", step.owner_text, re.I)):
            raise ValueError('unbound_conversation_action')
        if step.assumed_business and (step.context_mode != 'scenario' or step.assumed_business.casefold() not in body.message.casefold()
                                      or not contextual_language(body.message)):
            raise ValueError('unbound_business_context')
        if step.context_mode == 'scenario' and step.kind.startswith('favourites_'):
            raise ValueError('unbound_conversation_action')
    return plan


def help_text(topic, catalog):
    """Product knowledge, independent of how the owner phrases the question."""
    if topic == 'favourites':
        return ('Sign in, then tap the heart on a tool card to save it. Open Favourite tools to find your saved tools. '
                'Tap its heart again to remove it. You can also ask me to save or remove a named tool. '
                'Favourites are bookmarks, not subscriptions.')
    if topic == 'history':
        return ('Signed-in chats stay with your account for up to 30 days. Use Past conversations to reopen a chat '
                'and Load earlier messages for older turns. New chat starts a separate conversation. '
                'Delete history removes saved chat history. Guests keep a temporary chat in this browser tab; '
                'guest chats are not automatically imported when signing in.')
    if topic == 'account':
        return 'Sign in to keep account-owned chat history and favourite tools. Guests can browse and chat without an account.'
    if topic == 'comparison':
        return ('Tell me your business task and the tools you want to compare. Choose price, required plan, added cost, '
                'or features and fit. You can request a table and exclude tools. I use checked catalog evidence '
                'and explain any pricing details you need to confirm with the vendor.')
    if topic == 'businesses':
        return ('The directory includes ' + ', '.join(trade.name for trade in catalog.trades) +
                '. Other business types are welcome too: tell me your business and the task you want to improve. '
                'I can look for similar workflows without assuming a product suits your industry.')
    return ('This website helps business owners find software for everyday work, compare tools and plans, '
            'and decide what to try next. Browse tools by business or task, save favourites with the heart '
            'after signing in, or ask Arkadio for a comparison, including a table. Signed-in chat history '
            'is kept for up to 30 days. What would you like to explore?')


def forget_business(memory):
    memory.trade = memory.business_description = memory.business_goal = memory.scenario_business = None
    memory.business_forgotten = True
    memory.last_tool_ids = []
    memory.active_task_ids = []
    memory.pending_task_ids = []
    memory.pending_question = None
    memory.comparison_criterion = None
    memory.comparison_presentation = 'prose'
    memory.comparison_excluded_ids = []
    memory.background_done = False
