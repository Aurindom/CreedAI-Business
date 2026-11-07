from .schemas import BusinessProfile, Catalog, Fit, Option, ProblemCard, Recommendation, Route, SetAside, StackCheck, Tool
from .facts import tool_facts

ROUTE_ORDER: dict[Route, int] = {
    "already_have": 0,
    "check_plan": 1,
    "native_add_on": 2,
    "plan_upgrade": 3,
    "compatible_tool": 4,
    "separate_tool": 5,
    "switch": 6,
}
MAX_OPTIONS = 3


def _connects(tool: Tool, owned: list[Tool]) -> bool:
    if not tool.connects_to.known:
        return False
    return bool({o.id for o in owned} & set(tool.connects_to.value))


def _overlaps(tool: Tool, owned: list[Tool]) -> bool:
    for cap in tool.capabilities:
        if cap.level != "included":
            continue
        for other in owned:
            match = other.capability(cap.capability)
            if match and match.level == "included":
                return True
    return False


def _same(a, b) -> bool:
    return str(a).strip().casefold() == str(b).strip().casefold()


def _owned_route(tool: Tool, capability: str, plan: str | None) -> Route:
    """A feature counts as already paid for only when a sourced plan fact covers the owner's plan."""
    cap = tool.capability(capability)
    if cap is None or cap.level == "unknown":
        return "check_plan"
    if cap.level == "add_on":
        return "native_add_on"
    if not cap.included_from.known:
        return "check_plan"
    needed = cap.included_from.value
    if tool.entry_plan.known and _same(needed, tool.entry_plan.value):
        return "already_have"
    if plan and _same(plan, needed):
        return "already_have"
    need, have = tool.plan_rank(needed), tool.plan_rank(plan)
    if need is None or have is None:
        return "check_plan"
    return "already_have" if have >= need else "plan_upgrade"


def _route(tool: Tool, capability: str, owned: list[Tool], plan: str | None = None) -> Route:
    if tool in owned:
        return _owned_route(tool, capability, plan)
    if _connects(tool, owned):
        return "compatible_tool"
    return "switch" if _overlaps(tool, owned) else "separate_tool"


def _check_plan_note(tool: Tool, capability: str) -> str:
    cap = tool.capability(capability)
    if cap and cap.included_from.known:
        return f"Included from the {cap.included_from.value} plan. Check which plan you have"
    if cap and cap.level == "included":
        return "Listed as included, but not on which plans. Check your plan"
    return "Not confirmed whether your plan includes this. Check your plan"


def _monthly_cost(tool: Tool, capability: str, route: Route, plan: str | None = None) -> tuple[float | None, str]:
    cap = tool.capability(capability)
    addon = float(cap.addon_monthly_usd.value) if cap and cap.addon_monthly_usd.known else None

    if route == "already_have":
        return 0.0, "Included in what you already pay for"
    if route == "check_plan":
        return None, _check_plan_note(tool, capability)
    if route == "plan_upgrade":
        return None, f"Your {plan} plan does not include this. It starts on the {cap.included_from.value} plan"
    if route == "native_add_on":
        if addon is None:
            return None, "Add-on price or plan not confirmed. Verify with the vendor"
        return addon, "Add-on to what you already pay for"
    if not tool.entry_monthly_usd.known:
        return None, tool.entry_monthly_usd.note or "Price not published. Verify with the vendor"
    if cap is None or cap.level == "unknown":
        return None, "Not confirmed which plan includes this. Verify with the vendor"
    base = float(tool.entry_monthly_usd.value)
    if cap.level == "add_on":
        if addon is None:
            return None, "Add-on price not published. Verify with the vendor"
        return base + addon, "Entry plan plus the add-on, before processing or hardware fees"
    return base, "Entry plan, before processing or hardware fees"


def _fit(catalog: Catalog, tool: Tool, trade: str | None, owned: list[Tool]) -> tuple[Fit | None, str]:
    if tool in owned:
        return "you_use_it", "You already use this"
    fit = tool.fit(trade)
    if fit == "any_business":
        return fit, "Works for any kind of business"
    if fit == "made_for":
        return fit, f"Built for {catalog.trade_names([trade])} businesses"
    if tool.applicability == "unknown":
        return "unconfirmed", "Not yet confirmed which kinds of business this suits"
    if fit == "unconfirmed":
        return fit, f"Built for {catalog.trade_names(tool.trades)}. Check it suits your business"
    return None, f"Built for {catalog.trade_names(tool.trades)}, not {catalog.trade_names([trade])}"


def _option(tool: Tool, capability: str, owned: list[Tool], fit: Fit, fit_note: str, plan: str | None = None) -> Option:
    route = _route(tool, capability, owned, plan)
    cost, note = _monthly_cost(tool, capability, route, plan)
    return Option(
        tool_id=tool.id,
        tool_name=tool.name,
        route=route,
        fit=fit,
        fit_note=fit_note,
        added_monthly_usd=cost,
        cost_note=note,
        facts=tool_facts(tool),
    )


def _rank(options: list[Option]) -> list[Option]:
    return sorted(
        options,
        key=lambda o: (
            ROUTE_ORDER[o.route],
            o.fit != "made_for",
            o.added_monthly_usd is None,
            o.added_monthly_usd or 0,
            o.tool_name.casefold(),
        ),
    )[:MAX_OPTIONS]


def _tailoring_note(stated: str, trade: str | None, options: list[Option]) -> str | None:
    if trade is None and stated:
        return f"We don't have details for \"{stated}\" yet, so only tools that suit any business are ranked."
    if trade is None:
        return "You didn't tell us your type of business, so only tools that suit any business are ranked."
    if options and options[0].fit == "any_business":
        return "Nothing we've checked is built just for your kind of business, so these suit any business."
    return None


def recommend(catalog: Catalog, profile: BusinessProfile, problem: ProblemCard) -> Recommendation:
    """Eligibility is decided before ranking, so a tool made for another kind of business can never win on price or route."""
    owned = [catalog.tool(o.tool_id) for o in profile.owned]
    trade = catalog.resolve_trade(profile.trade)
    eligible, uncertain, set_aside = [], [], []
    for tool in catalog.tools:
        if tool.status == "rejected" or not tool.capability(problem.capability):
            continue
        fit, fit_note = _fit(catalog, tool, trade, owned)
        if fit is None:
            set_aside.append(SetAside(tool_id=tool.id, tool_name=tool.name, reason=fit_note))
            continue
        option = _option(tool, problem.capability, owned, fit, fit_note, profile.plan_for(tool.id))
        (uncertain if fit == "unconfirmed" else eligible).append(option)
    options = _rank(eligible)
    check_first = _rank(uncertain)
    note = _tailoring_note((profile.trade or "").strip(), trade, options)

    def result(outcome, winner, message):
        return Recommendation(
            problem_id=problem.id,
            outcome=outcome,
            winner_tool_id=winner,
            options=options,
            check_first=check_first,
            set_aside=set_aside,
            message=message,
            tailored=trade is not None and note is None,
            tailoring_note=note,
        )

    if not options and check_first:
        return result("verify_with_vendor", None, "Nothing is confirmed to suit you yet. Check these with the vendor first.")
    if not options:
        return result("no_match", None, "Nothing in the catalog fits this yet.")
    top = options[0]
    if top.route == "already_have":
        return result("no_new_tool", top.tool_id, f"No new tool needed. {top.tool_name} already covers this.")
    if top.route == "check_plan":
        return result("verify_with_vendor", None, f"{top.tool_name} may already include this. Check your plan before paying for anything new.")
    if top.route == "plan_upgrade":
        return result("verify_with_vendor", None, f"Your {top.tool_name} plan does not include this. Compare an upgrade with the other options.")
    if top.added_monthly_usd is None:
        return result("verify_with_vendor", None, "No clear winner until the vendor confirms the price or plan.")
    if top.route == "native_add_on":
        return result("add_on", top.tool_id, f"Add this to {top.tool_name}, which you already use.")
    if top.route == "switch":
        return result("new_tool", top.tool_id, f"{top.tool_name} covers this but overlaps what you have. Weigh the move first.")
    return result("new_tool", top.tool_id, f"{top.tool_name} is the best supported option for this.")


def check_stack(catalog: Catalog, tool_ids: list[str]) -> StackCheck:
    tools = [catalog.tool(tool_id) for tool_id in tool_ids]
    first_seen: dict[str, str] = {}
    duplicates = []
    for tool in tools:
        for cap in tool.capabilities:
            if cap.level != "included":
                continue
            if cap.capability in first_seen:
                duplicates.append(f"{first_seen[cap.capability]} and {tool.name} both cover {cap.capability}")
            first_seen.setdefault(cap.capability, tool.name)
    unknown = [tool.name for tool in tools if not tool.entry_monthly_usd.known]
    known = sum(float(tool.entry_monthly_usd.value) for tool in tools if tool.entry_monthly_usd.known)
    return StackCheck(
        duplicates=duplicates,
        known_monthly_usd=known,
        total_monthly_usd=None if unknown else known,
        unknown_cost_tools=unknown,
    )
