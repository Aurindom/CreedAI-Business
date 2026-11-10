"""Owner-described context and bounded conversational actions, never product facts.

Unknown businesses remain owner data. Catalog categories are optional, and cannot
be inferred into a claim that a vendor supports a regulated/specialist business.
"""
import ast
import operator
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict

from .agent.evidence import Claim, Source, _finish, _safe
from .comparison import compare


class ConversationAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['compare', 'recall', 'clarify', 'help', 'scope']
    criterion: Literal['price', 'plan', 'cost', 'fit'] | None = None
    owner_text: str


def business_description(message, pending=False):
    """Capture an explicit self-description, not arbitrary owner prose or instructions."""
    from .conversation_plan import contextual_language
    if contextual_language(message):
        return None
    if re.fullmatch(r"(?:hi|hello|hey|thanks|thank you|yes|no|skip.*|how are you.*)", message.strip(' .!?'), re.I):
        return None
    match = re.search(r"(?:^|[.!?]\s*|\b(?:actually|now)\s+)(?:i|we)\s+(?:own|run|operate)\s+an?\s+(.+)", message, re.I)
    if not match:
        match = re.search(r"\b(?:i|we)\s+(?:own|run|operate)\s+([^,;?!.]+\b(?:business|shop|store|clinic|company|practice|studio|farm|workshop))\b", message, re.I)
    if not match:
        match = re.search(r"\b(?:i|we)\s+have\s+(?:an?\s+)?([^,;?!.]+\b(?:business|shop|store|clinic|company|practice|studio))\b", message, re.I)
    if not match:
        match = re.search(r"\bmy business is\s+(.+)", message, re.I)
    if not match and pending and re.match(r"(?:what|which|how|why|when|can|could|would|do|does|is|are|i need|we need|help|find|compare|show)\b", message, re.I):
        return None
    value = match.group(1) if match else message if pending else ''
    value = re.split(r"[,;?!.]|\s+(?:and |but )?(?:how|now|please|can you|i need|we need)\b|\s+and\s+(?:(?:i|we)\s+)?(?:need|want|use|have|keep|am|are|handle|cannot|don't)\b", value, maxsplit=1, flags=re.I)[0]
    value = value.strip(' \"\'')
    if (not 2 <= len(value) <= 100 or not re.search(r'[a-zA-Z]{2}', value)
            or re.search(r'\b(?:not|never|instead of)\b', value, re.I)):
        return None
    return value


def criterion_for(message):
    text = message.casefold()
    if re.search(r'\b(?:total|overall|added|switching)\s+(?:monthly\s+)?cost|\bcost\b', text):
        return 'cost'
    if re.search(r'\b(?:cheapest|cheaper|price|prices|pricing|affordable|least expensive)\b', text):
        return 'price'
    if re.search(r'\b(?:plans?|tiers?|subscription)\b', text):
        return 'plan'
    if re.search(r'\b(?:features?|suitability|fit)\b', text):
        return 'fit'
    return None


def local_action(message, memory):
    """Conservative fast recognition; unfamiliar wording still has semantic routing."""
    text = message.casefold().strip(' .!?')
    if re.fullmatch(r'(?:do you (?:not )?|can you |please )?(?:remember|recall)(?: what)? (?:my |our |the )?(?:business|shop|store)(?: is)?', text):
        return 'recall', None
    criterion = criterion_for(message)
    if re.search(r"\b(?:do not|don't|dont|never)\s+compare\b", text):
        return None
    criterion_answer = bool(criterion and re.fullmatch(r'(?:by |the |on |required |overall |total |added |monthly |lowest |cheapest |their |price|prices|pricing|cost|plans?|tiers?|features?|fit|suitability|and|\s)+', text))
    if (re.search(r'\b(?:compare|comparison|versus|vs)\b', text)
            or (criterion and re.search(r'\b(?:cheapest|cheaper|least expensive)\b', text))
            or (criterion_answer and (memory.last_tool_ids or memory.pending_question == 'comparison'))):
        return 'compare', criterion
    return None


def small_answer(message):
    """Tiny arithmetic is local, bounded and never evaluated as executable code."""
    text = re.sub(r'^(?:what is|what\'s|calculate)\s+', '', message.casefold()).strip(' ?')
    if not re.fullmatch(r'[\d\s.+*/()\-]{3,60}', text):
        return None
    operations = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
    def value(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float) and abs(node.value) <= 1e9:
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in operations:
            result = operations[type(node.op)](value(node.left), value(node.right))
            if abs(result) <= 1e12:
                return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            return value(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        raise ValueError('unsupported arithmetic')
    try:
        result = value(ast.parse(text, mode='eval').body)
        return f'{result:g}. What would you like help with in your business?'
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, RecursionError):
        return None


def recall_text(memory):
    if memory.business_description or memory.trade:
        return f'You told me your business is {memory.business_description or memory.trade.replace("_", " ")}. What would you like to work on next?'
    return 'I do not have your business type in this conversation yet. What kind of business do you run?'


def comparison_package(catalog, profile, tasks, tool_ids, criterion):
    """Compare alternatives individually using the existing cost/plan engine.

    Read receipts cover every referenced tool. Unknown/inferred prices never win
    a cheapest calculation. Alternatives are not added together as a purchase.
    """
    sources = [Source(id='policy', kind='backend_policy')]
    claims = [Claim(id='comparison:scope', text=f'Comparing these alternatives by {criterion}. Each is considered separately; these are not a bundle to buy.', evidence_ids=['policy'])]
    ranked = []
    for tool_id in tool_ids:
        tool = catalog.tool(tool_id)
        result = compare(catalog, profile, tasks, [tool_id])
        fit = result.tools[0]
        refs = ['policy']
        for index, fact in enumerate(fit.facts):
            if fact.known and fact.checked and _safe(fact.source_url):
                sid = f'{tool_id}:comparison:{index}'
                sources.append(Source(id=sid, kind=fact.source_type or 'third_party', url=_safe(fact.source_url), checked=str(fact.checked), inferred=fact.inferred))
                refs.append(sid)
        details = list(dict.fromkeys(task.cost_note or task.reason for task in fit.tasks))
        text = f'{tool.name}: ' + ' '.join(details)
        price = tool.entry_monthly_usd
        if price and price.known and price.checked and _safe(price.source_url) and isinstance(price.value, (int, float)):
            text += f' Entry price: USD {price.value:g}/month' + (' (estimate).' if price.inferred else '.')
        plans = []
        for task in fit.tasks:
            capability = tool.capability(catalog.problem(task.problem_id).capability)
            plan = capability.included_from if capability and capability.level == 'included' else capability.addon_from if capability else None
            if plan and plan.known and plan.checked and _safe(plan.source_url):
                sid = f'{tool_id}:plan:{task.problem_id}'
                sources.append(Source(id=sid, kind=plan.source_type or 'third_party', url=_safe(plan.source_url), checked=str(plan.checked), inferred=plan.inferred))
                refs.append(sid)
                plans.append(str(plan.value) + (' (estimate)' if plan.inferred else ''))
        if plans:
            text += ' Required plan: ' + ', '.join(dict.fromkeys(plans)) + '.'
        if not fit.tasks:
            text += 'Task suitability needs confirmation.'
        stack = result.stack
        if stack and stack.total_monthly_usd is not None and stack.ready and not stack.estimated:
            ranked.append((stack.total_monthly_usd, tool.name))
        claims.append(Claim(id=f'{tool_id}:comparison', tool_id=tool_id, text=text, evidence_ids=refs))
    if criterion in ('price', 'cost'):
        if len(ranked) == len(tool_ids):
            minimum = min(price for price, _ in ranked)
            names = ', '.join(name for price, name in ranked if price == minimum)
            summary = f'Lowest confirmed added monthly cost for this task among these alternatives: {names}, USD {minimum:g}/month. This is not a claim about every product on the market.'
        else:
            summary = 'A cheapest suitable option cannot be confirmed across this shortlist because some required pricing, plan or suitability evidence is incomplete. Compare the confirmed details above before choosing.'
        # This is a backend calculation/limitation; each operand is independently
        # documented in its tool claim, as with the existing stack-cost engine.
        claims.append(Claim(id='comparison:cost', text=summary, evidence_ids=['policy']))
    ids = [claim.id for claim in claims]
    return _finish('ok', claims, sources, ids, [], {}, ids)
