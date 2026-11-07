from itertools import combinations

from .facts import tool_facts
from .matching import _facet_gap, _fit, _monthly_cost, _needed_plan, _option, _route
from .schemas import (
    BusinessProfile,
    Catalog,
    ComparedTool,
    Comparison,
    Connection,
    ProblemCard,
    StackCost,
    StackLine,
    TaskFit,
    TaskSlot,
    Tool,
)

MAX_COMPARED = 3
MAX_TASKS = 5
USABLE = ("eligible", "check_first")
FEES = "Monthly prices before processing, hardware, per-user or usage fees."


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _task_fit(catalog: Catalog, tool: Tool, problem: ProblemCard, profile: BusinessProfile, owned: list[Tool]) -> TaskFit | None:
    if not tool.capability(problem.capability):
        return None
    base = {"problem_id": problem.id, "title": problem.title}
    if tool.status == "rejected":
        return TaskFit(**base, standing="set_aside", reason="Taken out of the catalog after review")
    fit, fit_note = _fit(catalog, tool, catalog.resolve_trade(profile.trade), owned)
    if fit is None:
        return TaskFit(**base, standing="set_aside", reason=fit_note)
    gap = _facet_gap(catalog, tool, problem)
    option = _option(tool, problem.capability, owned, fit, gap or fit_note, profile.plan_for(tool.id))
    reason = option.fit_note
    if tool.status != "verified":
        reason += ". Our team hasn't rechecked its details yet"
    return TaskFit(
        **base,
        standing="check_first" if fit == "unconfirmed" or gap else "eligible",
        reason=reason,
        route=option.route,
        added_monthly_usd=option.added_monthly_usd,
        cost_note=option.cost_note,
    )


def _combined_new_cost(tool: Tool, capabilities: list[str]) -> tuple[float | None, str]:
    """A new buyer pays one plan that covers every chosen task plus each distinct add-on once, never one plan per task."""
    caps = [tool.capability(c) for c in capabilities]
    if any(c.level == "unknown" for c in caps):
        return None, "Not confirmed which plan includes all of these. Verify with the vendor"
    addons = [c for c in caps if c.level == "add_on"]
    if any(not c.addon_monthly_usd.known for c in addons):
        return None, "An add-on price is not published. Verify with the vendor"
    if tool.single_offering:
        price, label = tool.entry_monthly_usd, "The vendor's only offering"
    else:
        needed = [_needed_plan(c) for c in caps]
        if any(n is None for n in needed):
            return None, "Not confirmed which plan covers all of these. Verify with the vendor"
        ranks = [tool.plan_rank(n) for n in needed]
        if len({n.casefold() for n in needed}) > 1 and any(r is None for r in ranks):
            return None, f"These need the {_names(needed)} plans and their order isn't recorded. Verify with the vendor"
        top = needed[ranks.index(max(ranks))] if all(r is not None for r in ranks) else needed[0]
        price, label = tool.plan_price(top), f"{top} plan"
    if not price.known:
        return None, price.note or "Price not published. Verify with the vendor"
    total = float(price.value) + sum(float(c.addon_monthly_usd.value) for c in addons)
    return total, f"{label}{' plus add-ons' if addons else ''} covers all of these"


def _line(tool: Tool, fits: list[TaskFit], catalog: Catalog, profile: BusinessProfile, owned: list[Tool]) -> StackLine:
    capabilities = list(dict.fromkeys(catalog.problem(f.problem_id).capability for f in fits))
    base = {"tool_id": tool.id, "tool_name": tool.name, "problem_ids": [f.problem_id for f in fits]}
    if len(capabilities) == 1:
        return StackLine(**base, monthly_usd=fits[0].added_monthly_usd, note=fits[0].cost_note or "")
    if tool in owned:
        plan = profile.plan_for(tool.id)
        costs = [_monthly_cost(tool, c, _route(tool, c, owned, plan), plan) for c in capabilities]
        missing = next((note for cost, note in costs if cost is None), None)
        if missing:
            return StackLine(**base, monthly_usd=None, note=missing)
        return StackLine(**base, monthly_usd=sum(cost for cost, _ in costs), note="Added to what you already pay for")
    cost, note = _combined_new_cost(tool, capabilities)
    return StackLine(**base, monthly_usd=cost, note=note)


def _connections(catalog: Catalog, chosen: list[Tool], owned: list[Tool]) -> list[Connection]:
    """A connection counts only as far as a vendor's sourced list says. What moves, and which way, isn't recorded yet."""
    pool = chosen + [t for t in owned if t not in chosen]
    result = []
    for a, b in combinations(pool, 2):
        if a not in chosen and b not in chosen:
            continue
        listers = [x for x, y in ((a, b), (b, a)) if x.connects_to.known and y.id in x.connects_to.value]
        if listers:
            said = ". ".join(f"{x.name}'s vendor lists {y.name}" for x, y in ((a, b), (b, a)) if x in listers)
            note = f"{said}. What data moves between them, and which way, isn't recorded, so check before relying on it"
            result.append(Connection(tool_ids=[a.id, b.id], state="listed", listed_by=[x.id for x in listers], note=note, sources=[x.connects_to.source_url for x in listers]))
        else:
            result.append(Connection(tool_ids=[a.id, b.id], state="unverified", listed_by=[], note=f"We have no sourced record that {a.name} and {b.name} connect. Treat it as unverified"))
    return result


def _overlaps(catalog: Catalog, chosen: list[Tool]) -> list[str]:
    found = []
    for a, b in combinations(chosen, 2):
        shared = [c.capability for c in a.capabilities if c.level == "included" and (m := b.capability(c.capability)) and m.level == "included"]
        if shared:
            labels = _names([catalog.capability_label(s) for s in shared])
            found.append(f"{a.name} and {b.name} both list {labels}. That may be overlap, but it doesn't prove they do the same job")
    return found


def compare(catalog: Catalog, profile: BusinessProfile, problem_ids: list[str], tool_ids: list[str]) -> Comparison:
    """Tools picked for the same task are alternatives, so they are never added up as one purchase."""
    problems = [catalog.problem(p) for p in problem_ids]
    chosen = [catalog.tool(t) for t in tool_ids]
    owned = [catalog.tool(o.tool_id) for o in profile.owned]
    fits = {t.id: [f for p in problems if (f := _task_fit(catalog, t, p, profile, owned))] for t in chosen}
    usable = {t.id: [f for f in fits[t.id] if f.standing in USABLE] for t in chosen}

    slots = []
    for p in problems:
        covering = [t for t in chosen if any(f.problem_id == p.id for f in usable[t.id])]
        label = catalog.capability_label(p.capability)
        if not covering:
            slots.append(TaskSlot(problem_id=p.id, title=p.title, tool_ids=[], kind="gap", note=f"None of the chosen tools is a fit for {label}"))
        elif len(covering) == 1:
            slots.append(TaskSlot(problem_id=p.id, title=p.title, tool_ids=[covering[0].id], kind="covered", note=f"{covering[0].name} fills this"))
        else:
            names = _names([t.name for t in covering])
            slots.append(TaskSlot(problem_id=p.id, title=p.title, tool_ids=[t.id for t in covering], kind="alternatives", note=f"{names} are alternatives for {label}. You'd normally pick one"))

    compared = []
    for t in chosen:
        mine = usable[t.id]
        alone = [s.title for s in slots if s.tool_ids == [t.id]]
        if not mine:
            set_aside = [f.reason for f in fits[t.id] if f.standing == "set_aside"]
            role, note = "no_fit", set_aside[0] if set_aside else "It doesn't list any of the chosen tasks"
        elif alone:
            role, note = "fills_gap", f"Fills: {_names(alone)}"
        else:
            role, note = "alternative", "Another chosen tool also fits these tasks. Compare them rather than buying both"
        compared.append(ComparedTool(tool_id=t.id, tool_name=t.name, status=t.status, role=role, role_note=note, tasks=fits[t.id], facts=tool_facts(t)))

    stack, stack_note = None, ""
    buying = [t for t in chosen if usable[t.id]]
    if any(s.kind == "alternatives" for s in slots):
        stack_note = "Some chosen tools are alternatives for the same task, so they aren't added up as a bundle. Pick one per task first."
    elif not buying:
        stack_note = "None of the chosen tools fits these tasks."
    else:
        lines = [_line(t, usable[t.id], catalog, profile, owned) for t in buying]
        unknown = [line.tool_name for line in lines if line.monthly_usd is None]
        known = sum(line.monthly_usd for line in lines if line.monthly_usd is not None)
        total = None if unknown else known
        assumptions = [FEES]
        assumptions += [f"{t.name} is billed annually." for t in buying if t.entry_billing.known and t.entry_billing.value == "annual"]
        assumptions += [f"{t.name} still needs checking: {f.reason}." for t in buying for f in usable[t.id] if f.standing == "check_first"]
        budget = profile.budget_monthly_usd
        stack = StackCost(
            lines=lines,
            known_monthly_usd=known,
            total_monthly_usd=total,
            unknown_cost_tools=unknown,
            assumptions=assumptions,
            within_budget=None if budget is None or total is None else total <= budget,
        )
        gaps = [s.title for s in slots if s.kind == "gap"]
        stack_note = "Each tool covers a different task." + (f" Nothing chosen covers: {_names(gaps)}." if gaps else "")
    return Comparison(
        problem_ids=[p.id for p in problems],
        tools=compared,
        tasks=slots,
        overlaps=_overlaps(catalog, chosen),
        connections=_connections(catalog, chosen, owned),
        stack=stack,
        stack_note=stack_note,
    )
