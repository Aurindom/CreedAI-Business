from __future__ import annotations

import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable
from urllib.parse import urlsplit

from .contract import (
    CONTRACT_VERSION, HARD_CAPS, Candidate, ContractError, DiscoverInput, DiscoverResult, ErrorInfo,
    LimitsUsed, PageOutcome, SourceReport, Snapshot, failure, slugify, validate_request,
)
from .extract import Facts, extract_page, registrable_domain
from .sources import (
    Budget, Cancelled, FetchError, LimitReached, SafeFetcher, SearchAdapter, SearchContext, SearchQuery,
    WorkTimeout, run_bounded,
)
from .store import Store

MAX_LIST = 50
MAX_COMPARE = 6


@dataclass
class Deps:
    snapshot: Snapshot
    searches: list[SearchAdapter]
    fetcher: SafeFetcher
    store: Store
    kind: str = "fixture"
    clock: Callable[[], float] = time.monotonic
    today: Callable[[], date] = date.today


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").casefold()
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.casefold()}://{host}{path}{query}"


def _is_pricing_path(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return "pricing" in path or "/plans" in path


def _hypothesis_note(cand: Candidate, key: str) -> str | None:
    ctx = cand.hypotheses.get(key)
    return f"mentioned only in {ctx.replace('_', ' ')} text" if ctx else None


def assess(cand: Candidate, req: DiscoverInput, snapshot: Snapshot) -> Candidate:
    """Label how a stored candidate fits one request. The stored facts are not changed.

    Incompatible needs an explicit statement that the thing is not offered. A page that simply lists other
    capabilities, other facet values or other business types says nothing about the requested one, so that
    stays unconfirmed and the candidate stays in the research list.
    """
    incompatible: list[str] = []
    unconfirmed: list[str] = []
    notes: list[str] = []
    unresolved = set(cand.unresolved_fields)
    refused = set(cand.not_offered)

    cap_key = f"capability.{req.capability}"
    if req.capability not in cand.capabilities:
        if cap_key in refused:
            incompatible.append(f"pages say {req.capability} is not offered")
        else:
            note = _hypothesis_note(cand, cap_key)
            unconfirmed.append(f"{req.capability} {note}, not source-verified support" if note
                               else f"{req.capability} not stated on fetched pages")
            unresolved.add(cap_key)
    for facet_id, wanted in req.facets.items():
        listed = cand.facets.get(facet_id, [])
        if wanted in listed:
            continue
        key = f"facet.{facet_id}.{wanted}"
        if key in refused:
            incompatible.append(f"pages say {facet_id} {wanted} is not offered")
            continue
        note = _hypothesis_note(cand, key)
        if note:
            unconfirmed.append(f"{facet_id} {wanted} {note}")
        elif listed:
            unconfirmed.append(f"{facet_id} lists {', '.join(listed)} and does not state {wanted}")
        else:
            unconfirmed.append(f"{facet_id} {wanted} not stated")
        unresolved.add(f"facet.{facet_id}")
    if req.trade is not None:
        if req.trade not in snapshot.trades:
            notes.append(f"trade {req.trade!r} is not in the contract vocabulary, so no business-type check was applied")
        elif f"trade.{req.trade}" in refused:
            incompatible.append(f"pages say {req.trade} is not served")
        elif req.trade not in cand.applicability_trades and cand.applicability != "cross_industry":
            note = _hypothesis_note(cand, f"trade.{req.trade}")
            if note:
                unconfirmed.append(f"{req.trade} {note}")
            elif cand.applicability == "restricted":
                unconfirmed.append(f"vendor names {', '.join(cand.applicability_trades)} and does not state {req.trade}")
            else:
                unconfirmed.append(f"no business types stated, so {req.trade} is unconfirmed")
            unresolved.add("applicability")
    if incompatible:
        label, reason = "incompatible", "; ".join(incompatible)
    elif unconfirmed:
        label, reason = "unconfirmed", "; ".join(unconfirmed)
    else:
        label, reason = "matches", "states the requested task and every requested facet"
    if notes:
        reason = f"{reason}; {'; '.join(notes)}"
    return cand.model_copy(update={"compatibility": label, "compatibility_reason": reason, "unresolved_fields": sorted(unresolved)})


def _record(deps: Deps, facts: Facts, page_url: str, role: str, cid: str, vendor: str, domain: str, product: str, kind: str) -> None:
    deps.store.record_observation(
        cid, vendor, domain, product, page_url, role, kind, asdict(facts), None, deps.today(),
    )


def discover_tools(raw: Any, deps: Deps, cancel: threading.Event | None = None) -> dict[str, Any]:
    """Search, fetch, extract and store research candidates. The single entry point behind the MCP action."""
    run_id = uuid.uuid4().hex[:12]
    try:
        req = validate_request(raw, deps.snapshot)
    except ContractError as exc:
        return failure(exc.code, exc.message, run_id, deps.kind)

    budget = Budget(max_pages=req.max_pages, time_budget_s=req.time_budget_s, clock=deps.clock, cancel=cancel, ledger=deps.store)
    reports: list[SourceReport] = []
    outcomes: list[PageOutcome] = []
    touched: set[str] = set()
    done: dict[str, str] = {}
    stop = False

    known_trade = req.trade if req.trade in deps.snapshot.trades else None
    query = SearchQuery(req.capability, known_trade, dict(req.facets), limit=HARD_CAPS["max_results"] * 2)
    hits: list[str] = []
    for adapter in deps.searches:
        try:
            budget.allow_new_worker()
            budget.charge_search()
        except Cancelled:
            stop = True
            reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="skipped", reason_code="cancelled"))
            continue
        except LimitReached as lim:
            reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="limit_reached",
                                        reason_code=f"{lim.which}_limit"))
            continue
        ctx = SearchContext(remaining_s=max(0.0, budget.remaining), cancel=cancel)
        try:
            found = run_bounded(lambda: adapter.search(query, ctx), max(0.05, budget.remaining), cancel, budget.note_abandoned)
        except Cancelled:
            stop = True
            reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="skipped", reason_code="cancelled"))
            continue
        except WorkTimeout:
            reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="failed",
                                        reason_code="timeout", message="search did not answer within the time budget"))
            continue
        except Exception:
            reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="failed",
                                        reason_code="adapter_error", message="search adapter failed; details withheld"))
            continue
        fresh = [normalize_url(h.url) for h in found if h.url]
        hits.extend(u for u in fresh if u not in hits)
        reports.append(SourceReport(source_id=adapter.source_id, kind=adapter.kind, status="ok", hits=len(fresh)))

    def read(url: str) -> tuple[Any, str | None]:
        """Returns (page, None) or (None, outcome code). Raises LimitReached or Cancelled upward."""
        if url in done:
            return None, done[url]
        try:
            return deps.fetcher.fetch(url, budget), None
        except FetchError as exc:
            done[url] = exc.outcome
            outcomes.append(PageOutcome(url=url, outcome=exc.outcome, detail=exc.detail[:120] or None))
            return None, exc.outcome

    try:
        for url in hits:
            if url in done:
                continue
            page, bad = read(url)
            done.setdefault(url, "ok")
            if page is None:
                continue
            facts = extract_page(page.text, page.final_url, deps.snapshot)
            if facts.outcome != "ok":
                outcomes.append(PageOutcome(url=url, outcome=facts.outcome))
                continue
            if not facts.product:
                outcomes.append(PageOutcome(url=url, outcome="no_identity", detail="no product name on page"))
                continue
            domain = registrable_domain(urlsplit(page.final_url).hostname or "")
            cid = f"{domain}:{slugify(facts.product)}"
            role = "pricing" if _is_pricing_path(page.final_url) else "product"
            _record(deps, facts, page.final_url, role, cid, facts.vendor or domain, domain, facts.product, deps.kind)
            touched.add(cid)
            outcomes.append(PageOutcome(url=url, outcome="ok"))
            link = facts.pricing_link
            if role == "product" and link and normalize_url(link) not in done and normalize_url(link) != normalize_url(page.final_url):
                price_url = normalize_url(link)
                ppage, pbad = read(price_url)
                done.setdefault(price_url, "ok")
                if ppage is not None:
                    pfacts = extract_page(ppage.text, ppage.final_url, deps.snapshot)
                    if pfacts.outcome == "ok":
                        _record(deps, pfacts, ppage.final_url, "pricing", cid, facts.vendor or domain, domain, facts.product, deps.kind)
                        outcomes.append(PageOutcome(url=price_url, outcome="ok"))
                    else:
                        outcomes.append(PageOutcome(url=price_url, outcome=pfacts.outcome))
                        deps.store.record_observation(cid, facts.vendor or domain, domain, facts.product, ppage.final_url,
                                                      "pricing", deps.kind, None, pfacts.outcome, deps.today())
                elif pbad:
                    deps.store.record_observation(cid, facts.vendor or domain, domain, facts.product, price_url,
                                                  "pricing", deps.kind, None, pbad, deps.today())
    except LimitReached as lim:
        outcomes.append(PageOutcome(url="(remaining pages)", outcome="limit_reached", detail=f"{lim.which} limit"))
    except Cancelled:
        outcomes.append(PageOutcome(url="(remaining pages)", outcome="cancelled"))

    cancelled = bool(cancel is not None and cancel.is_set())
    deps.store.mark_seen(touched)
    matched: list[Candidate] = []
    excluded: list[Candidate] = []
    for cid in sorted(touched):
        stored = deps.store.get(cid)
        if stored is None:
            continue
        labeled = assess(stored, req, deps.snapshot)
        (excluded if labeled.compatibility == "incompatible" else matched).append(labeled)
    order = {"matches": 0, "unconfirmed": 1}
    matched.sort(key=lambda c: (order[c.compatibility], c.candidate_id))
    matched, excluded = matched[: req.max_results], excluded[: req.max_results]

    problems = [r for r in reports if r.status != "ok"] or [o for o in outcomes if o.outcome not in ("ok",)]
    any_source_ok = any(r.status in ("ok", "limit_reached") for r in reports)
    if not any_source_ok and not matched:
        status = "failed"
    elif problems or cancelled or budget.exhausted:
        status = "partial"
    else:
        status = "completed"
    error = ErrorInfo(code="all_sources_failed", message="no search source returned results") if status == "failed" else None
    result = DiscoverResult(
        contract_version=CONTRACT_VERSION, run_id=run_id, status=status, provenance=deps.kind,
        request=req.model_dump(mode="json"), candidates=matched, excluded=excluded,
        source_reports=reports, page_outcomes=outcomes, error=error,
        limits=LimitsUsed(
            pages_fetched=budget.pages - budget.searches, search_requests=budget.searches,
            abandoned_workers=budget.abandoned, bytes_fetched=budget.bytes, elapsed_s=round(budget.elapsed, 3),
            caps={**{k: float(v) for k, v in HARD_CAPS.items()}, "request_max_pages": float(req.max_pages),
                  "request_time_budget_s": req.time_budget_s},
            exhausted=budget.exhausted, cancelled=cancelled,
        ),
    )
    payload = result.model_dump(mode="json")
    deps.store.log_run(run_id, payload["request"], status, deps.kind,
                       {"candidates": [c.candidate_id for c in matched], "excluded": [c.candidate_id for c in excluded],
                        "pages": budget.pages - budget.searches, "searches": budget.searches})
    return payload


def get_candidate(candidate_id: Any, deps: Deps) -> dict[str, Any]:
    if not isinstance(candidate_id, str) or not candidate_id or len(candidate_id) > 200:
        return failure("invalid_input", "candidate_id must be a non-empty string", provenance=deps.kind)
    found = deps.store.get(candidate_id)
    if found is None:
        return failure("not_found", f"no stored candidate {candidate_id[:80]!r}", provenance=deps.kind)
    return {"contract_version": CONTRACT_VERSION, "status": "ok", "candidate": found.model_dump(mode="json")}


def list_candidates(raw: Any, deps: Deps) -> dict[str, Any]:
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"capability", "trade", "facets", "limit", "after"}:
        return failure("invalid_input", "allowed keys: capability, trade, facets, limit, after", provenance=deps.kind)
    limit = raw.get("limit", 20)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIST:
        return failure("invalid_input", f"limit must be 1..{MAX_LIST}", provenance=deps.kind)
    after = raw.get("after")
    if after is not None and not isinstance(after, str):
        return failure("invalid_input", "after must be a string", provenance=deps.kind)
    req = None
    if raw.get("capability") is not None:
        try:
            req = validate_request({k: raw[k] for k in ("capability", "trade", "facets") if k in raw}, deps.snapshot)
        except ContractError as exc:
            return failure(exc.code, exc.message, provenance=deps.kind)
    ids = deps.store.list_ids(limit, after)
    items: list[dict[str, Any]] = []
    for cid in ids:
        cand = deps.store.get(cid)
        if cand is None:
            continue
        if req is not None:
            cand = assess(cand, req, deps.snapshot)
        items.append(cand.model_dump(mode="json"))
    return {"contract_version": CONTRACT_VERSION, "status": "ok", "candidates": items,
            "next_after": ids[-1] if len(ids) == limit else None}


def compare_candidates(candidate_ids: Any, deps: Deps) -> dict[str, Any]:
    """Side by side stored facts. Unknown stays unknown, and no score or rank is produced."""
    if not isinstance(candidate_ids, list) or not 1 <= len(candidate_ids) <= MAX_COMPARE or not all(isinstance(c, str) for c in candidate_ids):
        return failure("invalid_input", f"candidate_ids must be 1..{MAX_COMPARE} strings", provenance=deps.kind)
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for cid in dict.fromkeys(candidate_ids):
        cand = deps.store.get(cid)
        if cand is None:
            missing.append(cid[:80])
            continue
        rows.append({
            "candidate_id": cand.candidate_id, "vendor": cand.vendor, "product": cand.product,
            "capabilities": cand.capabilities, "facets": cand.facets,
            "not_offered": cand.not_offered, "hypotheses": cand.hypotheses,
            "currencies": sorted({c or "unknown" for c in [p.currency for p in cand.pricing.plans] + [u.currency for u in cand.pricing.usage_charges]}),
            "applicability": cand.applicability, "applicability_trades": cand.applicability_trades,
            "pricing_state": cand.pricing.state,
            "plans": [p.model_dump(mode="json") for p in cand.pricing.plans],
            "usage_charges": [u.model_dump(mode="json") for u in cand.pricing.usage_charges],
            "pricing_note": cand.pricing.reason,
            "unresolved_fields": cand.unresolved_fields,
            "provenance": cand.provenance, "sources": cand.source_urls,
        })
    return {
        "contract_version": CONTRACT_VERSION, "status": "ok" if rows else "failed",
        "illustrative": True,
        "notice": "Stored research facts side by side. No ranking, score or recommendation.",
        "rows": rows, "missing": missing,
    }
