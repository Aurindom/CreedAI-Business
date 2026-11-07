from itertools import combinations

from .facts import tool_facts
from .matching import _facet_gap, _fit, _monthly_cost, _needed_plan, _option, _route
from .schemas import (
    AllInOne,
    BusinessProfile,
    Capability,
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

USABLE = ("eligible", "check_first")
FEES = "Monthly prices before processing, hardware, per-user or usage fees."
MAX_ALL_IN_ONE = 3


class AssignmentError(ValueError):
    pass


def _names(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _task_fit(catalog: Catalog, tool: Tool, problem: ProblemCard, profile: BusinessProfile, owned: list[Tool]) -> TaskFit | None:
    if not tool.capability(problem.capability):
        return None
    base = {"problem_id": problem.id, "title": problem.title}
    if tool.status == "rejected":
        return TaskFit(**base, standing="set_aside", coverage="excluded", reason="Taken out of the catalog after review")
    fit, fit_note = _fit(catalog, tool, catalog.resolve_trade(profile.trade), owned)
    if fit is None:
        return TaskFit(**base, standing="set_aside", coverage="excluded", reason=fit_note)
    gap = _facet_gap(catalog, tool, problem)
    option = _option(tool, problem.capability, owned, fit, gap or fit_note, profile.plan_for(tool.id))
    reason = option.fit_note
    if tool.status != "verified":
        reason += ". Our team hasn't rechecked its details yet"
    standing = "check_first" if fit == "unconfirmed" or gap else "eligible"
    return TaskFit(
        **base,
        standing=standing,
        coverage="confirmed" if standing == "eligible" and tool.status == "verified" else "possible",
        reason=reason,
        route=option.route,
        added_monthly_usd=option.added_monthly_usd,
        cost_note=option.cost_note,
    )


def _addon_total(addons: list[Capability]) -> tuple[float | None, str | None]:
    """Add-ons are charged once per sourced offer. Without a recorded offer we can't tell one pack from two, so the total stays unknown."""
    if any(not c.addon_monthly_usd.known for c in addons):
        return None, "An add-on price is not published. Verify with the vendor"
    if len(addons) < 2:
        return sum(float(c.addon_monthly_usd.value) for c in addons), None
    if any(not c.addon_offer.known for c in addons):
        return None, "Not recorded whether these add-ons are one purchase or separate ones. Verify with the vendor"
    offers: dict[str, set[float]] = {}
    for c in addons:
        offers.setdefault(str(c.addon_offer.value), set()).add(float(c.addon_monthly_usd.value))
    if any(len(prices) > 1 for prices in offers.values()):
        return None, "The same add-on is recorded at different prices. Verify with the vendor"
    return sum(next(iter(prices)) for prices in offers.values()), None


def _combined_new_cost(tool: Tool, capabilities: list[str]) -> tuple[float | None, str]:
    """A new buyer pays one plan that covers every chosen task plus each distinct add-on once, never one plan per task."""
    caps = [tool.capability(c) for c in capabilities]
    if any(c.level == "unknown" for c in caps):
        return None, "Not confirmed which plan includes all of these. Verify with the vendor"
    addon_cost, addon_note = _addon_total([c for c in caps if c.level == "add_on"])
    if addon_cost is None:
        return None, addon_note
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
    total = float(price.value) + addon_cost
    return total, f"{label}{' plus add-ons' if addon_cost else ''} covers all of these"


def _line(tool: Tool, fits: list[TaskFit], catalog: Catalog, profile: BusinessProfile, owned: list[Tool]) -> StackLine:
    capabilities = list(dict.fromkeys(catalog.problem(f.problem_id).capability for f in fits))
    base = {
        "tool_id": tool.id,
        "tool_name": tool.name,
        "problem_ids": [f.problem_id for f in fits],
        "confirmed": all(f.coverage == "confirmed" for f in fits),
    }
    if len(capabilities) == 1:
        return StackLine(**base, monthly_usd=fits[0].added_monthly_usd, note=fits[0].cost_note or "")
    if tool in owned:
        plan = profile.plan_for(tool.id)
        routes = {c: _route(tool, c, owned, plan) for c in capabilities}
        costs = [_monthly_cost(tool, c, r, plan) for c, r in routes.items()]
        missing = next((note for cost, note in costs if cost is None), None)
        if missing:
            return StackLine(**base, monthly_usd=None, note=missing)
        cost, note = _addon_total([tool.capability(c) for c, r in routes.items() if r == "native_add_on"])
        return StackLine(**base, monthly_usd=cost, note=note or "Added to what you already pay for")
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


def _role(tool: Tool, usable: list[TaskFit], slots: list[TaskSlot], all_fits: list[TaskFit]) -> tuple[str, str]:
    mine = [s for s in slots if s.assigned_to == tool.id]
    if not usable:
        set_aside = [f.reason for f in all_fits if f.standing == "set_aside"]
        return "no_fit", set_aside[0] if set_aside else "It doesn't list any of the chosen tasks"
    if mine:
        titles = _names([s.title for s in mine])
        if all(s.kind == "covered" for s in mine):
            return "fills_gap", f"Fills: {titles}"
        return "might_fill_gap", f"Might fill: {titles}. Some of this still needs checking"
    if any(s.kind == "alternatives" and tool.id in s.tool_ids for s in slots):
        return "alternative", "Another chosen tool also fits these tasks. Compare them rather than buying both"
    return "not_needed", "Other chosen tools already cover the tasks it fits, so it isn't counted"


def _marginal(tool: Tool, held: list[TaskFit], extra: TaskFit, catalog: Catalog, profile: BusinessProfile, owned: list[Tool]) -> float | None:
    after = _line(tool, held + [extra], catalog, profile, owned).monthly_usd
    before = _line(tool, held, catalog, profile, owned).monthly_usd
    return None if after is None or before is None else after - before


def _assign(
    catalog: Catalog,
    profile: BusinessProfile,
    problems: list[ProblemCard],
    chosen: list[Tool],
    owned: list[Tool],
    usable: dict[str, list[TaskFit]],
    assignments: dict[str, str],
) -> list[TaskSlot]:
    """Each task goes to one tool. Confirmed fits beat possible ones, and a tool already needed for another task is suggested before buying around it."""
    fit_of = {(t.id, f.problem_id): f for t in chosen for f in usable[t.id]}
    by_id = {t.id: t for t in chosen}
    pools, held = {}, {t.id: [] for t in chosen}
    for p in problems:
        candidates = [t for t in chosen if (t.id, p.id) in fit_of]
        chosen_for = assignments.get(p.id)
        if chosen_for is not None:
            if (chosen_for, p.id) not in fit_of:
                raise AssignmentError(f"{by_id[chosen_for].name} isn't a usable fit for {p.title}, so it can't be assigned to it")
            pools[p.id] = (candidates, [by_id[chosen_for]], True)
            continue
        confirmed = [t for t in candidates if fit_of[(t.id, p.id)].coverage == "confirmed"]
        pools[p.id] = (candidates, confirmed or candidates, False)
    for p in problems:
        pool = pools[p.id][1]
        if len(pool) == 1:
            held[pool[0].id].append(fit_of[(pool[0].id, p.id)])

    slots = []
    for p in problems:
        candidates, pool, explicit = pools[p.id]
        label = catalog.capability_label(p.capability)
        base = {"problem_id": p.id, "title": p.title, "candidate_ids": [t.id for t in candidates]}
        if not candidates:
            slots.append(TaskSlot(**base, tool_ids=[], kind="gap", note=f"None of the chosen tools is a fit for {label}"))
            continue
        suggested, pick = False, pool[0] if len(pool) == 1 else None
        if pick is None:
            anchored = [t for t in pool if held[t.id]]
            if anchored:
                costs = {t.id: _marginal(t, held[t.id], fit_of[(t.id, p.id)], catalog, profile, owned) for t in anchored}
                pick = min(anchored, key=lambda t: (costs[t.id] is None, costs[t.id] or 0.0, chosen.index(t)))
                held[pick.id].append(fit_of[(pick.id, p.id)])
                suggested = True
        if pick is None:
            names = _names([t.name for t in pool])
            slots.append(TaskSlot(**base, tool_ids=[t.id for t in pool], kind="alternatives", note=f"{names} are alternatives for {label}. You'd normally pick one"))
            continue
        kind = "covered" if fit_of[(pick.id, p.id)].coverage == "confirmed" else "possible"
        if suggested:
            note = f"{pick.name} is already needed for another task, so we suggest it here too. You can choose differently"
        elif explicit:
            note = f"You chose {pick.name} for this"
        elif kind == "covered":
            note = f"{pick.name} fills this"
        else:
            note = f"{pick.name} might fill this, but it still needs checking"
        slots.append(TaskSlot(**base, tool_ids=[pick.id], kind=kind, note=note, assigned_to=pick.id, suggested=suggested))
    return slots


def _all_in_one(catalog: Catalog, profile: BusinessProfile, problems: list[ProblemCard], chosen: list[Tool], owned: list[Tool]) -> tuple[list[AllInOne], str]:
    """Shown beside the owner's choice for comparison. It is never swapped in and never described as cheaper."""
    if len(problems) < 2:
        return [], ""
    found = []
    for t in catalog.tools:
        if t in chosen or t.status == "rejected":
            continue
        fits = [_task_fit(catalog, t, p, profile, owned) for p in problems]
        if any(f is None or f.standing not in USABLE for f in fits):
            continue
        coverage = "confirmed" if all(f.coverage == "confirmed" for f in fits) else "possible"
        line = _line(t, fits, catalog, profile, owned)
        note = line.note if coverage == "confirmed" else f"{line.note}. Its fit for some of these still needs checking"
        found.append(AllInOne(tool_id=t.id, tool_name=t.name, status=t.status, coverage=coverage, monthly_usd=line.monthly_usd, note=note))
    found.sort(key=lambda a: a.coverage != "confirmed")
    if not found:
        return [], "No single tool in our catalog lists all of these tasks. A wider search isn't available yet"
    return found[:MAX_ALL_IN_ONE], "Tools that list every chosen task, shown for comparison only. They aren't swapped into your choice"


def compare(
    catalog: Catalog,
    profile: BusinessProfile,
    problem_ids: list[str],
    tool_ids: list[str],
    assignments: dict[str, str] | None = None,
) -> Comparison:
    """Tools that fit the same task are alternatives unless one is assigned, so they are never added up as one purchase."""
    problems = [catalog.problem(p) for p in problem_ids]
    chosen = [catalog.tool(t) for t in tool_ids]
    owned = [catalog.tool(o.tool_id) for o in profile.owned]
    fits = {t.id: [f for p in problems if (f := _task_fit(catalog, t, p, profile, owned))] for t in chosen}
    usable = {t.id: [f for f in fits[t.id] if f.standing in USABLE] for t in chosen}
    slots = _assign(catalog, profile, problems, chosen, owned, usable, assignments or {})

    compared = []
    for t in chosen:
        role, note = _role(t, usable[t.id], slots, fits[t.id])
        compared.append(ComparedTool(tool_id=t.id, tool_name=t.name, status=t.status, role=role, role_note=note, tasks=fits[t.id], facts=tool_facts(t)))

    given = {s.problem_id: s.assigned_to for s in slots if s.assigned_to}
    assigned = {t.id: [f for f in usable[t.id] if given.get(f.problem_id) == t.id] for t in chosen}
    buying = [t for t in chosen if assigned[t.id]]
    stack, stack_note = None, ""
    if any(s.kind == "alternatives" for s in slots):
        stack_note = "Some chosen tools are alternatives for the same task, so they aren't added up as a bundle. Pick one per task first."
    elif not buying:
        stack_note = "None of the chosen tools fits these tasks."
    else:
        lines = [_line(t, assigned[t.id], catalog, profile, owned) for t in buying]
        unknown = [line.tool_name for line in lines if line.monthly_usd is None]
        unconfirmed = [line.tool_name for line in lines if not line.confirmed]
        known = sum(line.monthly_usd for line in lines if line.monthly_usd is not None)
        total = None if unknown else known
        ready = not unknown and not unconfirmed
        assumptions = [FEES]
        assumptions += [f"{t.name} is billed annually." for t in buying if t.entry_billing.known and t.entry_billing.value == "annual"]
        assumptions += [f"{t.name} still needs checking: {f.reason}." for t in buying for f in assigned[t.id] if f.coverage == "possible"]
        budget = profile.budget_monthly_usd
        if budget is not None and not ready:
            assumptions.append(f"Your budget is ${budget:g}/mo. The parts we could price come to ${known:g}/mo, but that isn't a confirmed total yet.")
        stack = StackCost(
            lines=lines,
            known_monthly_usd=known,
            total_monthly_usd=total,
            unknown_cost_tools=unknown,
            assumptions=assumptions,
            within_budget=total <= budget if ready and budget is not None else None,
            ready=ready,
            unconfirmed=unconfirmed,
        )
        gaps = [s.title for s in slots if s.kind == "gap"]
        stack_note = "Each task goes to one tool."
        if any(s.suggested for s in slots):
            stack_note += " Some tasks went to a tool you already need for another task. You can change that."
        if unconfirmed:
            stack_note += f" Still to check: {_names(unconfirmed)}."
        if gaps:
            stack_note += f" Nothing chosen covers: {_names(gaps)}."
    all_in_one, all_in_one_note = _all_in_one(catalog, profile, problems, chosen, owned)
    return Comparison(
        problem_ids=[p.id for p in problems],
        tools=compared,
        tasks=slots,
        overlaps=_overlaps(catalog, chosen),
        connections=_connections(catalog, chosen, owned),
        stack=stack,
        stack_note=stack_note,
        all_in_one=all_in_one,
        all_in_one_note=all_in_one_note,
    )
