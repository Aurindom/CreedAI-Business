"""Trusted answer packages for Penny; never use owner/history numbers as facts."""
from .agent.evidence import Claim, Source, _finish, _safe, build_evidence, build_request_evidence
from .tasks import affirmative_excerpt, owner_excerpts, resolve_task
import re


class ActionContextError(ValueError):
    pass


TASK_QUESTION = 'What would you like help with?'


def plan_already_unknown(body):
    """Recognize explicit uncertainty; an omitted profile field alone is insufficient."""
    text = body.message.casefold().replace('’', "'")
    if re.search(r"\b(?:do not know|don't know|dont know|not sure|unsure)\b[^.!?]{0,60}\bplan\b", text):
        return True
    if text.strip(' .!?') in {'i do not know', "i don't know", 'i dont know', 'not sure', 'i am not sure'}:
        previous = next((item.text.casefold() for item in reversed(body.history) if item.role == 'assistant'), '')
        return 'plan' in previous
    return False


def filtered_context(catalog, profile, memory):
    excluded = set(memory.ruled_out)
    clean_catalog = catalog.model_copy(update={
        'tools': [tool for tool in catalog.tools if tool.id not in excluded]
    })
    clean_profile = profile.model_copy(update={
        'owned': [entry for entry in profile.owned if entry.tool_id not in excluded]
    })
    return clean_catalog, clean_profile


def task_ids(catalog, body):
    # History supplies a pending answer's context, never an arbitrary short turn.
    normalized = body.message.casefold().strip(' .!?')
    known = {card.id for card in catalog.problem_cards}
    pending = pending_tasks(catalog, body)
    if normalized in {'yes', 'yes please', 'please do', 'sure', 'go ahead'} and len(pending) == 1:
        return pending
    if re.fullmatch(r'(?:please )?show (?:me )?(?:the )?(?:tools|options|recommendations) for that(?: now)?', normalized):
        active = [pid for pid in body.memory.active_task_ids if pid in known]
        if len(active) == 1:
            return active
    texts = [body.message]
    previous = next((item.text for item in reversed(body.history) if item.role == 'assistant'), '')
    answering = body.memory.pending_question in ('business', 'software', 'budget', 'plan')
    answering = answering or any(question(catalog, key)['question'].casefold() in previous.casefold()
                                 for key in ('business', 'software', 'budget', 'plan'))
    if answering or plan_already_unknown(body):
        texts += [item.text for item in reversed(body.history) if item.role == 'user']
    for text in texts:
        match = resolve_task(catalog, text)
        if match.status == 'matched':
            return [match.problem_id]
        if match.status == 'ambiguous':
            return []
    if body.memory.pending_question in ('business', 'software', 'budget', 'plan'):
        known = {card.id for card in catalog.problem_cards}
        return [pid for pid in body.memory.active_task_ids if pid in known]
    return []


def selected_task_ids(catalog, body, arguments):
    """Bind semantic choices to owner evidence, distinguishing separate needs from ambiguity."""
    selected = str(arguments.get('problem_id', ''))
    catalog.problem(selected)
    if selected in task_ids(catalog, body):
        return [selected]
    excerpt = arguments.get('task_text')
    if not isinstance(excerpt, str) or not 1 <= len(excerpt) <= 500:
        raise ActionContextError('Task needs an exact owner excerpt')
    current = resolve_task(catalog, body.message)
    choices = [card.id for card in current.choices]
    excerpt_match = resolve_task(catalog, excerpt)
    specific_excerpt = excerpt_match.status == 'matched' and excerpt_match.problem_id == selected
    separate_need = (excerpt_match.status == 'unsupported' and excerpt in owner_excerpts(body.message)
                     and excerpt.strip() != body.message.strip())
    if (current.status == 'matched' and not separate_need) or (current.status == 'ambiguous' and choices != [selected]
                                      and not (selected in choices and specific_excerpt)):
        raise ActionContextError('Do not override the current task or its ambiguity')
    pending = pending_tasks(catalog, body)
    if (current.status == 'unsupported' and pending == [selected]
            and affirmative_excerpt(body.message, excerpt)):
        return [selected]
    if len(excerpt) < 3:
        raise ActionContextError('A new task needs a meaningful owner excerpt')
    if current.status == 'unsupported' and len(pending) > 1 and selected in pending:
        if excerpt.casefold().strip() != catalog.problem(selected).title.casefold().strip():
            raise ActionContextError('Choose which pending task before recommending one')
    sources = [body.message, *(item.text for item in reversed(body.history) if item.role == 'user')]
    for source in sources:
        if not affirmative_excerpt(source, excerpt):
            continue
        match = resolve_task(catalog, source)
        if (match.status == 'unsupported' or (match.status == 'matched' and match.problem_id == selected)
                or (source == body.message and separate_need)
                or (match.status == 'ambiguous' and ([card.id for card in match.choices] == [selected]
                    or (selected in [card.id for card in match.choices] and specific_excerpt)))):
            return [selected]
    raise ActionContextError('Task excerpt must come from an affirmative owner request')


def pending_tasks(catalog, body):
    known = {card.id for card in catalog.problem_cards}
    pending = [pid for pid in body.memory.pending_task_ids if pid in known]
    if pending:
        return pending
    previous = next((item.text for item in reversed(body.history) if item.role == 'assistant'), '')
    return [card.id for card in catalog.problem_cards if f'Explore: {card.title}' in previous]


def question_repeats(catalog, profile, body, key):
    if key in ('task', 'business', 'software', 'budget') and task_ids(catalog, body):
        return True
    if key == 'business' and profile.trade:
        return True
    if key == 'software' and profile.owned:
        return True
    if key == 'budget' and profile.budget_monthly_usd is not None:
        return True
    try:
        prompt = (TASK_QUESTION if key == 'task' else question(catalog, key)['question']).casefold()
    except ValueError:
        return False
    return any(prompt in item.text.casefold() for item in body.history if item.role == 'assistant')


def request_package(catalog, profile, body):
    tasks = task_ids(catalog, body)
    return (build_evidence(catalog, profile, tasks) if tasks
            else build_request_evidence(catalog, profile, body.message))


def qualify_package(catalog, package, body=None):
    """Do not present zero entry price as unlimited use; do not invent quotas."""
    from . import chat_guard
    if chat_guard.reason(package.model_dump(mode='json'), include_personal=False):
        return build_evidence(catalog, None, [], available=False)
    claims = list(package.claims)
    required = list(package.required_claim_ids)
    defaults = list(package.default_claim_ids)
    tool_ids = {claim.tool_id for claim in claims if claim.tool_id}
    for tool_id in sorted(tool_ids):
        tool = catalog.tool(tool_id)
        fact = tool.entry_monthly_usd
        if fact.known and float(fact.value) == 0:
            cid = f'{tool_id}:free_limits'
            claims.append(Claim(id=cid, tool_id=tool_id,
                                text=f'{tool.name}: free-plan usage limits, paid upgrades and task-specific availability still need checking.',
                                evidence_ids=['policy'], state='unconfirmed'))
            required.append(cid)
            defaults.append(cid)
    followups = dict(package.followups)
    if body is not None and plan_already_unknown(body):
        followups.pop('plan', None)
    return _finish(package.status, claims, list(package.sources), required,
                   list(package.winner_tool_ids), followups, defaults)


def details_package(tools):
    claims = []
    sources = [Source(id='policy', kind='backend_policy')]
    for tool in tools:
        cid = f'{tool.id}:details'
        text = f'{tool.name}: '
        refs = ['policy']
        fact = tool.entry_monthly_usd
        if fact.known and fact.checked and _safe(fact.source_url):
            sid = f'{tool.id}:entry'
            sources.append(Source(id=sid, kind=fact.source_type or 'third_party',
                                  url=_safe(fact.source_url), checked=str(fact.checked),
                                  inferred=fact.inferred))
            refs.append(sid)
            label = 'Estimated published entry price' if fact.inferred else 'Published entry price'
            text += f'{label}: USD {float(fact.value):g}/month. '
            if float(fact.value) == 0:
                text += 'Free-plan usage limits and paid upgrades need checking. '
        else:
            text += 'Published entry price is not confirmed. '
        if tool.entry_billing.known and tool.entry_billing.value == 'annual':
            text += 'The listed monthly equivalent requires annual billing. '
        text += ('This is an entry price, not a task-specific quote or a combined purchase total. '
                 'Required tiers, usage charges and suitability need checking. ')
        if tool.status != 'verified':
            text += 'This catalog entry is pending review. '
        claims.append(Claim(id=cid, tool_id=tool.id, text=text, evidence_ids=refs,
                            state='unconfirmed'))
    ids = [claim.id for claim in claims]
    return _finish('ok', claims, sources, ids, [], {}, ids)


def action_package(catalog, profile, body, name, arguments):
    if name == 'recommend_tools':
        return build_evidence(catalog, profile, selected_task_ids(catalog, body, arguments))
    if name == 'get_tool_details':
        return details_package([catalog.tool(str(arguments['tool_id']))])
    if name == 'compare_tools':
        ids = arguments.get('tool_ids', [])
        if not isinstance(ids, list) or not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
            raise ValueError('Choose two or three distinct tools')
        tasks = task_ids(catalog, body)
        if tasks:
            return build_evidence(catalog, profile, tasks, ids)
        return details_package([catalog.tool(tool_id) for tool_id in ids])
    return request_package(catalog, profile, body)


def question(catalog, key, problem_ids=None):
    if key == 'business':
        return {'question': 'What kind of business do you run?',
                'choices': [trade.name for trade in catalog.trades[:3]] + ['Skip these questions']}
    if key == 'software':
        return {'question': 'Which software do you already use?',
                'choices': ['I will type the names', 'No software yet', 'Skip these questions']}
    if key == 'budget':
        return {'question': 'What can you add to your monthly software bill?',
                'choices': ['$0 added', 'I will type my budget', 'Skip these questions']}
    if key == 'plan':
        return {'question': 'Which subscription plan do you currently have?',
                'choices': ['I will use the plan picker', 'I do not know']}
    if key == 'task':
        if (not isinstance(problem_ids, list) or not 2 <= len(problem_ids) <= 3
                or not all(isinstance(pid, str) for pid in problem_ids)
                or len(set(problem_ids)) != len(problem_ids)):
            raise ValueError('Choose two or three distinct catalog tasks')
        try:
            cards = [catalog.problem(pid) for pid in problem_ids]
        except KeyError:
            raise ValueError('Choose known catalog tasks') from None
        return {'question': TASK_QUESTION,
                'choices': [card.title for card in cards] + ['Browse other tasks']}
    raise ValueError('Choose a supported question')
