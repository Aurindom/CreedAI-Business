"""Request-scoped statements derived from marketplace policy, not model knowledge.

Sources are provenance, not newly verified web evidence. Raw summaries and vendor
instructions are deliberately not eligible answer statements.
"""
from __future__ import annotations

import hashlib
import json
from urllib.parse import urlsplit
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ..comparison import compare
from ..discovery import public_url
from ..domains import registrable_domain
from ..matching import recommend
from ..schemas import BusinessProfile, Catalog, Fact
from ..tasks import resolve_task


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Source(Strict):
    id: str
    kind: Literal["vendor", "third_party", "backend_policy"]
    url: str | None = None
    checked: str | None = None
    inferred: bool = False


class Claim(Strict):
    id: str
    tool_id: str | None = None
    text: str
    evidence_ids: list[str]
    state: Literal["policy", "sourced", "estimate", "unconfirmed"] = "policy"


class EvidencePackage(Strict):
    version: Literal["1"] = "1"
    package_id: str
    status: Literal["ok", "unavailable"]
    claims: list[Claim]
    sources: list[Source]
    required_claim_ids: list[str]
    winner_tool_ids: list[str]
    followups: dict[str, str]
    default_claim_ids: list[str]


OUTCOMES = {
    "no_new_tool": "Your existing subscription covers this need; you may not need a new tool.",
    "add_on": "An add-on to your existing software is the backend's supported option.",
    "new_tool": "The backend found a supported option. Review its fit, cost and switching implications.",
    "verify_with_vendor": "No confirmed winner yet. Verify the plan, fit or price before buying.",
    "no_match": "Let's explore another way to help: compare nearby tasks or outline what a custom tool would need. A suitable product has not been confirmed yet.",
}
ROUTES = {
    "already_have": "Your recorded subscription includes this task.",
    "check_plan": "Check your subscription plan before buying anything new.",
    "native_add_on": "This task is available through an add-on to your software.",
    "plan_upgrade": "Your recorded plan needs an upgrade for this task; compare alternatives first.",
    "compatible_tool": "The catalog records a connection to software you already use.",
    "separate_tool": "This is a separate tool to consider for the task.",
    "switch": "This overlaps software you use; consider the effort of switching.",
}


def _safe(url: object) -> str | None:
    value = str(url) if url else None
    return value if value and public_url(value, allow_reserved=False) is None else None


def _finish(status, claims, sources, required, winners, followups, default) -> EvidencePackage:
    content = dict(status=status, claims=claims, sources=sources,
                   required_claim_ids=required, winner_tool_ids=winners,
                   followups=followups, default_claim_ids=default)
    serial = json.dumps(content, sort_keys=True, default=lambda x: x.model_dump())
    return EvidencePackage(package_id=hashlib.sha256(serial.encode()).hexdigest()[:24], **content)


def build_request_evidence(catalog: Catalog, profile: BusinessProfile, text: str,
                           suggested: list[str] | None = None) -> EvidencePackage:
    """Resolve owner words without forcing unfamiliar tasks into an unrelated match.

    Alternatives are browsing choices, not recommendations that solve the original
    request. Unknown/ambiguous input remains internal resolver state.
    """
    match = resolve_task(catalog, text)
    if match.status == "matched":
        return build_evidence(catalog, profile, [match.problem_id])
    followups = {"custom_steps": "Would you like to outline the steps a custom tool would need?"}
    if match.choices:
        message = "Let's narrow that down. Which of these tasks is closest to what you need?"
        choices = match.choices[:5]
    else:
        message = ("What would you like help with? Choose an outcome you want, browse these tasks, or outline a custom workflow together."
                   if not text.strip() else
                   "Let's break that into the outcome you want. You can explore these tasks, or outline a custom workflow together.")
        # Tasks that fit the owner's business when the caller knows them; otherwise the first five.
        choices = [catalog.problem(pid) for pid in suggested] if suggested else catalog.problem_cards[:5]
    for card in choices:
        followups[f"task:{card.id}"] = f"Explore: {card.title}"
    claim = Claim(id="clarify", text=message, evidence_ids=["policy"])
    return _finish("ok", [claim], [Source(id="policy", kind="backend_policy")], ["clarify"], [], followups, ["clarify"])


def build_evidence(catalog: Catalog, profile: BusinessProfile, problem_ids: list[str],
                   tool_ids: list[str] | None = None,
                   assignments: dict[str, str] | None = None, *, available: bool = True) -> EvidencePackage:
    """One adapter over recommend/compare. Caller supplies validated catalog tasks.

    Optional comparison uses the existing stack accounting without reimplementing
    addon deduplication. No product summaries are treated as sourced descriptions.
    """
    sources = [Source(id="policy", kind="backend_policy")]
    claims: list[Claim] = []
    required, winners, default = [], [], []
    followups = {}
    if not available:
        claims = [Claim(id="unavailable", text="The catalog search did not work. Keep browsing or try again later.", evidence_ids=["policy"])]
        return _finish("unavailable", claims, sources, ["unavailable"], [], {}, ["unavailable"])
    if not 1 <= len(problem_ids) <= 5 or len(set(problem_ids)) != len(problem_ids):
        raise ValueError("provide one to five distinct catalog tasks")

    def source(key: str, fact: Fact) -> list[str]:
        url = _safe(fact.source_url)
        if not url or not fact.checked:
            return []
        if not any(s.id == key for s in sources):
            sources.append(Source(id=key, kind=fact.source_type or "third_party", url=url,
                                  checked=fact.checked.isoformat(), inferred=fact.inferred))
        return [key]

    for pid in problem_ids:
        problem = catalog.problem(pid)
        rec = recommend(catalog, profile, problem)
        decision_id = f"{pid}:decision"
        claims.append(Claim(id=decision_id, text=f"{problem.title}: {OUTCOMES[rec.outcome]}", evidence_ids=["policy"]))
        required.append(decision_id)
        default.append(decision_id)
        if rec.winner_tool_id and rec.winner_tool_id not in winners:
            winners.append(rec.winner_tool_id)
        if rec.tailoring_note:
            cid = f"{pid}:business"
            trade = catalog.resolve_trade(profile.trade)
            if trade is not None and rec.options and rec.options[0].fit == "any_business":
                business_note = "For this need, the leading option is general-purpose rather than industry-specific. Check any specialised workflow requirements."
                state = "policy"
            elif not (profile.trade or "").strip():
                business_note = "We are matching your stated need. Your business type was not supplied; general-purpose options are shown where supported, and other possibilities need checking."
                state = "unconfirmed"
            else:
                business_note = "We are matching your stated need, but have not mapped your business type. General-purpose options are shown where supported; industry-specific suitability is not confirmed."
                state = "unconfirmed"
            claims.append(Claim(id=cid, text=business_note, evidence_ids=["policy"], state=state))
            required.append(cid)
            default.append(cid)
        if rec.check_first:
            followups["workflow"] = "Which workflow or channel must this support so we can check the fit?"
        if rec.outcome == "no_match":
            followups["custom_steps"] = "Would you like a draft checklist for a custom tool instead?"
        for option in [*rec.options[:3], *rec.check_first[:2]]:
            tool = catalog.tool(option.tool_id)
            cap = tool.capability(problem.capability)
            ids = ["policy"]
            if cap:
                ids += source(f"{tool.id}:{problem.capability}:access", cap.access)
                ids += source(f"{tool.id}:{problem.capability}:plan", cap.included_from if cap.level == "included" else cap.addon_from)
                ids += source(f"{tool.id}:{problem.capability}:addon", cap.addon_monthly_usd)
            ids += source(f"{tool.id}:entry", tool.entry_monthly_usd)
            ids += source(f"{tool.id}:tiers", tool.plan_prices)
            if _safe(tool.applicability_source):
                key = f"{tool.id}:applicability"
                if not any(s.id == key for s in sources):
                    sources.append(Source(id=key, kind="vendor", url=_safe(tool.applicability_source)))
                ids.append(key)
            uncertain = option in rec.check_first or option.status != "verified"
            text = f"{tool.name}: "
            text += "Possible option only; its suitability or details need checking." if uncertain else ROUTES[option.route]
            if option.fit == "any_business":
                text += " Listed as general-purpose, offered across industries."
            elif option.fit == "unconfirmed":
                text += " Business suitability is not confirmed; check the required workflow."
            price_source = any(i.endswith(":entry") or i.endswith(":tiers") or i.endswith(":addon") for i in ids)
            if option.price_estimated and option.added_monthly_usd is not None and price_source:
                text += f" Estimated added cost: USD {option.added_monthly_usd:g}/month. Confirm assumptions and terms; this is not a confirmed budget fit."
                state = "estimate"
            elif option.added_monthly_usd is not None and not uncertain and (price_source or option.route == "already_have"):
                text += f" Added cost recorded by the backend: USD {option.added_monthly_usd:g}/month."
                state = "sourced" if len(ids) > 1 else "unconfirmed"
            else:
                text += " Comparable added cost is not confirmed."
                state = "unconfirmed"
            if tool.entry_billing.known and tool.entry_billing.value == "annual":
                text += " Listed monthly equivalent requires annual billing."
                ids += source(f"{tool.id}:billing", tool.entry_billing)
            if option.within_budget is False:
                text += " Above your stated added monthly budget."
            if option.price_estimated or option.added_monthly_usd is None or uncertain or state == "unconfirmed":
                pricing = _safe(tool.entry_monthly_usd.source_url)
                if (tool.entry_monthly_usd.source_type != "vendor" or
                    registrable_domain(urlsplit(pricing or "").hostname or "") != registrable_domain(urlsplit(str(tool.url)).hostname or "")):
                    pricing = None
                url = pricing or _safe(tool.url)
                text += f" Check official pricing and plan details: {url}" if url else " Official pricing link needs checking."
            cid = f"{pid}:{tool.id}"
            claims.append(Claim(id=cid, tool_id=tool.id, text=text, evidence_ids=list(dict.fromkeys(ids)), state=state))
            if option.tool_id == rec.winner_tool_id or len(default) < 4:
                default.append(cid)
            if option.route in {"check_plan", "plan_upgrade"}:
                followups["plan"] = "Which subscription plan do you currently have?"
        if rec.options or rec.check_first:
            followups["compare"] = "Would you like to compare these options and their plan requirements?"
            followups["custom_steps"] = "Would you like a draft checklist for a custom tool instead?"
    if tool_ids:
        result = compare(catalog, profile, problem_ids, tool_ids, assignments)
        stack = result.stack
        text = "Selected stack: "
        if stack and stack.total_monthly_usd is not None:
            text += f"USD {stack.total_monthly_usd:g}/month added cost or conditional subtotal. "
        if stack and stack.estimated:
            text += "Includes estimates; confirm pricing assumptions. "
        text += "Ready under current catalog rules." if stack and stack.ready else "Not confirmed ready; review missing coverage, pricing and plan requirements."
        claims.append(Claim(id="stack", text=text, evidence_ids=["policy"]))
        required.append("stack")
        default.append("stack")
    return _finish("ok", claims, sources, required, winners, followups, list(dict.fromkeys(default)))
