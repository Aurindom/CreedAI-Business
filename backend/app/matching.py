from .schemas import BusinessProfile, Capability, Catalog, Fit, Option, ProblemCard, Recommendation, Route, SetAside, StackCheck, Tool
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
OWNED_ROUTES: set[Route] = {"already_have", "check_plan", "native_add_on", "plan_upgrade"}
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


def _needed_plan(cap: Capability) -> str | None:
    source = cap.included_from if cap.level == "included" else cap.addon_from
    return str(source.value) if source.known else None


def _covers(tool: Tool, needed: str, plan: str | None) -> bool | None:
    """None means the owner's plan can't be placed against the needed tier, so nobody gets told yes or no.
    Even an entry-plan feature needs a recognised plan, because a missing or legacy plan may predate it."""
    if plan and _same(plan, needed):
        return True
    need, have = tool.plan_rank(needed), tool.plan_rank(plan)
    if need is None or have is None:
        return None
    return have >= need


def _owned_route(tool: Tool, capability: str, plan: str | None) -> Route:
    """A feature counts as already paid for only when a sourced plan fact covers the owner's plan."""
    cap = tool.capability(capability)
    if cap is None or cap.level == "unknown":
        return "check_plan"
    if tool.single_offering:
        return "already_have" if cap.level == "included" else "native_add_on"
    needed = _needed_plan(cap)
    if needed is None:
        return "native_add_on" if cap.level == "add_on" else "check_plan"
    covered = _covers(tool, needed, plan)
    if covered is None:
        return "check_plan"
    if not covered:
        return "plan_upgrade"
    return "already_have" if cap.level == "included" else "native_add_on"


def _route(tool: Tool, capability: str, owned: list[Tool], plan: str | None = None) -> Route:
    if tool in owned:
        return _owned_route(tool, capability, plan)
    if _connects(tool, owned):
        return "compatible_tool"
    return "switch" if _overlaps(tool, owned) else "separate_tool"


def _check_plan_note(tool: Tool, capability: str) -> str:
    cap = tool.capability(capability)
    if cap and cap.level == "add_on" and cap.addon_from.known:
        return f"Available as an add-on from the {cap.addon_from.value} plan. Check which plan you have"
    if cap and cap.included_from.known:
        return f"Included from the {cap.included_from.value} plan. Check which plan you have"
    if cap and cap.level == "included":
        return "Listed as included, but not on which plans. Check your plan"
    return "Not confirmed whether your plan includes this. Check your plan"


ESTIMATE_NOTE = "Part of this price is our estimate, so check the vendor's pricing page"


def estimated(note: str, inferred: bool) -> tuple[str, bool]:
    """A price read with some inference is still shown, but it is labelled and kept out of confirmed totals."""
    return (f"{note}. {ESTIMATE_NOTE}" if inferred else note), inferred


def _monthly_cost(tool: Tool, capability: str, route: Route, plan: str | None = None) -> tuple[float | None, str, bool]:
    cap = tool.capability(capability)
    addon = float(cap.addon_monthly_usd.value) if cap and cap.addon_monthly_usd.known else None

    if route == "already_have":
        return 0.0, "Included in what you already pay for", False
    if route == "check_plan":
        return None, _check_plan_note(tool, capability), False
    if route == "plan_upgrade":
        if cap.level == "add_on":
            return None, f"Your {plan} plan can't add this. The add-on needs the {_needed_plan(cap)} plan", False
        return None, f"Your {plan} plan does not include this. It starts on the {_needed_plan(cap)} plan", False
    if route == "native_add_on":
        if addon is None:
            return None, "Add-on price or plan not confirmed. Verify with the vendor", False
        if not tool.single_offering and not cap.addon_from.known:
            return None, f"The add-on is ${addon:g}/mo, but which plans can add it isn't confirmed. Check with the vendor", False
        return addon, *estimated("Add-on to what you already pay for", cap.addon_monthly_usd.inferred)
    return _new_buyer_cost(tool, cap, addon)


def _new_buyer_cost(tool: Tool, cap: Capability | None, addon: float | None) -> tuple[float | None, str, bool]:
    """A new buyer pays for the plan the feature needs, so the cheapest plan's price is never borrowed for a higher tier."""
    if not tool.entry_monthly_usd.known and not tool.plan_prices.known:
        return None, tool.entry_monthly_usd.note or "Price not published. Verify with the vendor", False
    if cap is None or cap.level == "unknown":
        return None, "Not confirmed which plan includes this. Verify with the vendor", False
    if cap.level == "add_on" and addon is None:
        return None, "Add-on price not published. Verify with the vendor", False
    if tool.single_offering:
        price, label = tool.entry_monthly_usd, "The vendor's only offering"
    else:
        needed = _needed_plan(cap)
        if needed is None:
            what = "which plans can add this" if cap.level == "add_on" else "which plan includes this"
            return None, f"Not confirmed {what}. Verify with the vendor", False
        price, label = tool.plan_price(needed), f"{needed} plan"
    if not price.known:
        return None, price.note or "Price not published. Verify with the vendor", False
    billing = ", billed annually" if tool.entry_billing.known and tool.entry_billing.value == "annual" else ""
    base = float(price.value)
    if cap.level == "add_on":
        return base + addon, *estimated(f"{label} plus the add-on{billing}, before processing or hardware fees", price.inferred or cap.addon_monthly_usd.inferred)
    return base, *estimated(f"{label}{billing}, before processing or hardware fees", price.inferred)


def _fit(catalog: Catalog, tool: Tool, trade: str | None, owned: list[Tool]) -> tuple[Fit | None, str]:
    if tool in owned:
        return "you_use_it", "You already use this"
    fit = tool.fit(trade)
    if fit == "any_business":
        return fit, "The vendor offers this to many kinds of business"
    if fit == "made_for":
        return fit, f"Built for {catalog.trade_names([trade])} businesses"
    if tool.applicability == "unknown":
        return "unconfirmed", "Not yet confirmed which kinds of business this suits"
    if fit == "unconfirmed":
        return fit, f"Built for {catalog.trade_names(tool.trades)}. Check it suits your business"
    return None, f"Built for {catalog.trade_names(tool.trades)}, not {catalog.trade_names([trade])}"


def _option(tool: Tool, capability: str, owned: list[Tool], fit: Fit, fit_note: str, plan: str | None = None) -> Option:
    route = _route(tool, capability, owned, plan)
    cost, note, is_estimate = _monthly_cost(tool, capability, route, plan)
    return Option(
        tool_id=tool.id,
        tool_name=tool.name,
        status=("pending_review" if tool.origin == "discovered" and tool.auto_review
                and (not tool.auto_review.eligible or tool.auto_review.capability != capability) else tool.status),
        route=route,
        fit=fit,
        fit_note=fit_note,
        added_monthly_usd=cost,
        cost_note=note,
        facts=tool_facts(tool),
        price_estimated=is_estimate,
    )


def _facet_gap(catalog: Catalog, tool: Tool, problem: ProblemCard) -> str | None:
    """A card that needs a specific channel or kind of work only counts a tool when a sourced fact confirms it."""
    cap = tool.capability(problem.capability)
    for facet_id, wanted in problem.requires.items():
        stated = cap.facets.get(facet_id) if cap else None
        if not (stated and stated.known and wanted in stated.value):
            facet = catalog.facet(facet_id)
            return f"Not confirmed it handles {facet.describe(wanted)}. Check with the vendor"
    return None


def _budget(option: Option, budget: float | None) -> Option:
    if budget is not None and option.added_monthly_usd is not None and not option.price_estimated:
        option.within_budget = option.added_monthly_usd <= budget
    return option


def _rank(options: list[Option]) -> list[Option]:
    """Among tools the owner would newly buy, a checked tool outranks an unchecked one before route or price count."""
    return sorted(
        options,
        key=lambda o: (
            o.route not in OWNED_ROUTES,
            o.route not in OWNED_ROUTES and o.status != "verified",
            ROUTE_ORDER[o.route],
            o.fit != "made_for",
            o.added_monthly_usd is None,
            o.added_monthly_usd or 0,
            o.tool_name.casefold(),
        ),
    )[:MAX_OPTIONS]


def _tailoring_note(stated: str, trade: str | None, options: list[Option]) -> str | None:
    if trade is None and stated:
        return f"We don't have details for \"{stated}\" yet, so only tools the vendor offers to many kinds of business are ranked."
    if trade is None:
        return "You didn't tell us your type of business, so only tools the vendor offers to many kinds of business are ranked."
    if options and options[0].fit == "any_business":
        return "Nothing we've checked is built just for your kind of business, so these are offered to many kinds of business."
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
            set_aside.append(SetAside(tool_id=tool.id, tool_name=tool.name, status=tool.status, reason=fit_note))
            continue
        gap = _facet_gap(catalog, tool, problem)
        option = _option(tool, problem.capability, owned, fit, gap or fit_note, profile.plan_for(tool.id))
        _budget(option, profile.budget_monthly_usd)
        (uncertain if fit == "unconfirmed" or gap else eligible).append(option)
    options = _rank(eligible)
    check_first = _rank(uncertain)
    note = _tailoring_note((profile.trade or "").strip(), trade, options)
    budget = profile.budget_monthly_usd
    budget_note = None if budget is None else f"Your budget of ${budget:g}/mo is compared with what each option adds to your monthly bill, not your total bill. Options with an unconfirmed cost aren't counted as fitting."

    def result(outcome, winner, message):
        if winner and options[0].within_budget is False:
            message += f" It adds more than your ${budget:g}/mo budget."
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
            budget_note=budget_note,
        )

    if not options and check_first:
        return result("verify_with_vendor", None, "Nothing is confirmed to suit you yet. Check these with the vendor first.")
    if not options:
        return result("no_match", None, "Nothing in the catalog fits this yet.")
    top = options[0]
    if top.status != "verified":
        review = catalog.tool(top.tool_id).auto_review
        if review:
            if review.capability != problem.capability:
                return result("verify_with_vendor", None, f"{top.tool_name} has not been automatically checked for this task. Confirm its plan and feature support.")
            return result("verify_with_vendor", None,
                          f"{top.tool_name}: automatic evidence checks are complete. " + " ".join(review.notes[:2]))
        if top.route in OWNED_ROUTES:
            return result("verify_with_vendor", None, f"{top.tool_name}, which you use, may cover this, but our team hasn't rechecked its details yet. Check with the vendor before paying for anything new.")
        return result("verify_with_vendor", None, f"{top.tool_name} looks like a fit, but our team hasn't rechecked its details yet. Confirm with the vendor first.")
    if top.route == "already_have":
        return result("no_new_tool", top.tool_id, f"No new tool needed. {top.tool_name} already covers this.")
    if top.route == "check_plan":
        return result("verify_with_vendor", None, f"{top.tool_name} may already include this. Check your plan before paying for anything new.")
    if top.route == "plan_upgrade":
        return result("verify_with_vendor", None, f"Your {top.tool_name} plan does not include this. Compare an upgrade with the other options.")
    if top.added_monthly_usd is None:
        return result("verify_with_vendor", None, "No clear winner until the vendor confirms the price or plan.")
    if top.price_estimated:
        return result("verify_with_vendor", None, f"{top.tool_name} looks like the best fit, but part of its price is our estimate. Check the vendor's pricing page before paying.")
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
                duplicates.append(f"{first_seen[cap.capability]} and {tool.name} both cover {catalog.capability_label(cap.capability)}")
            first_seen.setdefault(cap.capability, tool.name)
    unknown = [tool.name for tool in tools if not tool.entry_monthly_usd.known]
    known = sum(float(tool.entry_monthly_usd.value) for tool in tools if tool.entry_monthly_usd.known)
    estimates = [tool.name for tool in tools if tool.entry_monthly_usd.known and tool.entry_monthly_usd.inferred]
    return StackCheck(
        duplicates=duplicates,
        known_monthly_usd=known,
        total_monthly_usd=None if unknown else known,
        unknown_cost_tools=unknown,
        estimated_cost_tools=estimates,
    )
