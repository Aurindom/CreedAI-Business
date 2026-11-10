"""Checked comparison presentation; the model never supplies table cells or prices."""
from pydantic import BaseModel, ConfigDict, Field

from .comparison import compare
from .agent.evidence import _safe


class TableSource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    url: str = Field(max_length=2000)
    checked: str = Field(max_length=30)


class TableRow(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tool_id: str = Field(max_length=100)
    tool: str = Field(max_length=200)
    plan: str = Field(max_length=400)
    entry_price: str = Field(max_length=200)
    added_cost: str = Field(max_length=200)
    notes: str = Field(max_length=1000)
    sources: list[TableSource] = Field(max_length=6)


class ComparisonTable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(max_length=200)
    criterion: str = Field(max_length=20)
    rows: list[TableRow] = Field(min_length=1, max_length=6)


def build(catalog, profile, tasks, ids, criterion):
    rows = []
    for tid in ids:
        tool = catalog.tool(tid)
        result = compare(catalog, profile, tasks, [tid])
        fit = result.tools[0]
        plans, sources = [], []
        for pid in tasks:
            capability = tool.capability(catalog.problem(pid).capability)
            plan = (capability.included_from if capability.level == 'included' else capability.addon_from) if capability else None
            if plan and plan.known and plan.checked and _safe(plan.source_url):
                plans.append(str(plan.value) + (' (estimate)' if plan.inferred else ''))
                sources.append(TableSource(url=_safe(plan.source_url), checked=str(plan.checked)))
        price = tool.entry_monthly_usd
        price_known = bool(price and price.known and price.checked and _safe(price.source_url))
        if price_known:
            sources.append(TableSource(url=_safe(price.source_url), checked=str(price.checked)))
        stack = result.stack
        added = (f'USD {stack.total_monthly_usd:g}/month' + (' (estimate)' if stack.estimated else '')
                 if stack and stack.total_monthly_usd is not None else 'Confirm required plan and fees')
        if stack and stack.total_monthly_usd is not None and not stack.ready:
            added += ' (needs plan confirmation)'
        rows.append(TableRow(tool_id=tid, tool=tool.name, plan=', '.join(dict.fromkeys(plans)) or 'Confirm with vendor',
            entry_price=f'USD {price.value:g}/month' + (' (estimate)' if price.inferred else '') if price_known and isinstance(price.value, (int, float)) else 'Confirm with vendor',
            added_cost=added,
            notes=' '.join(dict.fromkeys(task.cost_note or task.reason for task in fit.tasks))[:1000] or 'Confirm suitability for your task',
            sources=list({source.url + source.checked: source for source in sources}.values())[:6]))
    return ComparisonTable(title='Compare alternatives', criterion=criterion, rows=rows)


def valid_surface(item):
    try:
        first, second = item['protocol']
        created, updated = first['createSurface'], second['updateComponents']
        component, = updated['components']
        if (first['version'] != 'v0.9' or second['version'] != 'v0.9'
                or created['catalogId'] != 'https://mainstreet.ai/catalogs/penny/v1'
                or not created['surfaceId'].startswith('penny-table-') or len(created['surfaceId']) > 100
                or updated['surfaceId'] != created['surfaceId']
                or component['id'] != 'root' or component['component'] != 'PennyComparisonTable'
                or item['text'] != component['title']):
            return False
        value = ComparisonTable.model_validate({key: value for key, value in component.items() if key not in ('id', 'component')})
        return all(_safe(source.url) for row in value.rows for source in row.sources)
    except (ValueError, KeyError, TypeError):
        return False
