"""App side of tool discovery.

A finder (fixture today, the sandbox worker's fetcher later) searches and reads vendor pages and returns a
contract 1.1.0 result. This module never fetches anything itself. It runs the finder inside a time limit,
checks the result against the catalog vocabulary, turns each supported candidate into a pending tool and
saves it. Page text is never copied into a tool, so vendor wording can't reach the agent as instructions.
"""

import ipaddress
import sqlite3
import threading
import uuid
from collections.abc import Callable
from datetime import date
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from . import db
from .domains import identity, registrable_domain, slug
from .schemas import Capability, Catalog, Fact, Tool

CONTRACT_VERSION = "1.1.0"
MAX_RESULTS = 10
MAX_PAGES = 16
MAX_SECONDS = 30.0
GRACE_SECONDS = 2.0
INTERNAL_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain", ".lan", ".home", ".corp")
RESERVED_SUFFIXES = (".test", ".example", ".invalid")
NOTICE = "Found by discovery. Nobody has reviewed these facts yet, so check them on the vendor's site."


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability: str = Field(min_length=1, max_length=60)
    trade: str | None = Field(default=None, max_length=60, pattern=r"^[A-Za-z0-9 _-]+$")
    facets: dict[str, str] = Field(default_factory=dict)
    max_results: int = Field(default=5, ge=1, le=MAX_RESULTS)
    max_pages: int = Field(default=6, ge=1, le=MAX_PAGES)
    time_budget_s: float = Field(default=15.0, gt=0, le=MAX_SECONDS)


class Evidence(BaseModel):
    field: str
    url: str
    excerpt: str = Field(max_length=240)
    checked: date
    source_kind: Literal["fixture", "live"]


class PricePlan(BaseModel):
    name: str | None = None
    amount: float = Field(ge=0)
    currency: str | None = None
    unit: str
    billing: Literal["monthly", "annual", "unspecified"] = "unspecified"
    source_url: str


class UsageCharge(BaseModel):
    amount: float = Field(ge=0)
    currency: str | None = None
    per: str
    source_url: str


class Pricing(BaseModel):
    state: Literal["fixed", "usage_based", "quote_only", "unknown", "extraction_failed"] = "unknown"
    plans: list[PricePlan] = Field(default_factory=list)
    usage_charges: list[UsageCharge] = Field(default_factory=list)


class Candidate(BaseModel):
    candidate_id: str
    vendor: str
    vendor_domain: str
    product: str = Field(min_length=1, max_length=80)
    product_url: str
    pricing_url: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    facets: dict[str, list[str]] = Field(default_factory=dict)
    not_offered: list[str] = Field(default_factory=list)
    applicability: Literal["cross_industry", "restricted", "unknown"] = "unknown"
    applicability_trades: list[str] = Field(default_factory=list)
    pricing: Pricing = Field(default_factory=Pricing)
    compatibility: Literal["matches", "incompatible", "unconfirmed"] = "unconfirmed"
    evidence: list[Evidence] = Field(default_factory=list)
    discovery_status: Literal["research_candidate"] = "research_candidate"


class Limits(BaseModel):
    pages_fetched: int = 0
    elapsed_s: float = 0.0


class ErrorInfo(BaseModel):
    code: str
    message: str = Field(max_length=300)


class FinderResult(BaseModel):
    contract_version: str
    run_id: str
    status: Literal["completed", "partial", "failed"]
    provenance: Literal["fixture", "live", "mixed"]
    candidates: list[Candidate] = Field(default_factory=list)
    limits: Limits | None = None
    error: ErrorInfo | None = None

    @field_validator("contract_version")
    @classmethod
    def same_version(cls, value: str) -> str:
        if value != CONTRACT_VERSION:
            raise ValueError(f"expected contract_version {CONTRACT_VERSION}, got {value}")
        return value


class Skipped(BaseModel):
    candidate_id: str
    reason: str
    tool_id: str | None = None


class DiscoveryReport(BaseModel):
    run_id: str
    status: Literal["completed", "partial", "failed"]
    added: list[str] = Field(default_factory=list)
    updated: list[str] = Field(default_factory=list)
    duplicates: list[Skipped] = Field(default_factory=list)
    excluded: list[Skipped] = Field(default_factory=list)
    error: ErrorInfo | None = None
    notice: str = NOTICE


Finder = Callable[[DiscoveryRequest, threading.Event], Any]


class DiscoveryFailed(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def public_url(url: str, allow_reserved: bool) -> str | None:
    """A static check of a url found by discovery. Returns why it is unsafe, or None.

    The fetcher also resolves and pins addresses. This check stops anything that should never be stored
    or shown as a vendor link, even when the finder got it wrong.
    """
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "bad url"
    host = (parts.hostname or "").rstrip(".").casefold()
    if parts.scheme != "https":
        return "not https"
    if parts.username or parts.password:
        return "credentials in url"
    if port not in (None, 443):
        return "unusual port"
    if host == "localhost" or host.endswith(INTERNAL_SUFFIXES):
        return "internal host name"
    try:
        ipaddress.ip_address(host.strip("[]"))
        return "bare ip address"
    except ValueError:
        pass
    if not host or "." not in host:
        return "no public host name"
    if host.endswith(RESERVED_SUFFIXES) and not allow_reserved:
        return "reserved test domain"
    if host.replace(".", "").isdigit() or host.startswith("0x"):
        return "numeric host"
    return None


def check_request(catalog: Catalog, request: DiscoveryRequest) -> None:
    """Discovery only looks for tasks and facet values the catalog already knows, so nothing new enters the vocabulary."""
    known = {c for category in catalog.categories for c in category.capabilities}
    if request.capability not in known:
        raise DiscoveryFailed("unknown_capability", f"unknown task: {request.capability}")
    facets = {f.id: f for f in catalog.facets}
    for facet_id, value in request.facets.items():
        facet = facets.get(facet_id)
        if facet is None or request.capability not in facet.capabilities or value not in facet.values:
            raise DiscoveryFailed("unknown_facet", f"unknown filter for this task: {facet_id}={value}")


def run_finder(catalog: Catalog, request: DiscoveryRequest, finder: Finder, allow_fixture: bool = False) -> FinderResult:
    """Runs the finder in its own thread so a stuck finder can't hold the caller past the time budget.

    A Python thread can't be killed. On timeout the cancel event is set, the thread is left to finish on
    its own and anything it returns later is ignored.
    """
    check_request(catalog, request)
    cancel = threading.Event()
    box: dict[str, Any] = {}

    def work() -> None:
        try:
            box["raw"] = finder(request, cancel)
        except Exception as exc:
            box["error"] = type(exc).__name__

    worker = threading.Thread(target=work, name="discovery-finder", daemon=True)
    worker.start()
    worker.join(request.time_budget_s + GRACE_SECONDS)
    if worker.is_alive():
        cancel.set()
        raise DiscoveryFailed("timed_out", f"discovery took longer than {request.time_budget_s:g} seconds and was stopped")
    if "error" in box:
        raise DiscoveryFailed("finder_error", f"the finder failed ({box['error']})")
    try:
        result = FinderResult.model_validate(box.get("raw"))
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "result"
        raise DiscoveryFailed("bad_result", f"the finder's result broke the contract at {where}: {first['msg']}") from None
    if result.provenance != "live" and not allow_fixture:
        raise DiscoveryFailed("not_live", "this result came from test pages, so it can't be saved here")
    limits = result.limits
    if limits is None:
        raise DiscoveryFailed("over_budget", "the finder did not report the pages and time it used")
    if limits.pages_fetched > request.max_pages:
        raise DiscoveryFailed("over_budget", f"the finder read {limits.pages_fetched} pages, more than the {request.max_pages} allowed")
    if limits.elapsed_s > request.time_budget_s + GRACE_SECONDS:
        raise DiscoveryFailed("over_budget", f"the finder ran {limits.elapsed_s:g} seconds, more than the {request.time_budget_s:g} allowed")
    if len(result.candidates) > request.max_results:
        raise DiscoveryFailed("over_budget", f"the finder returned {len(result.candidates)} candidates, more than the {request.max_results} allowed")
    return result


def _sourced(evidence: list[Evidence], field: str, domain: str) -> Evidence | None:
    """Only evidence from the vendor's own site counts. A review site or a comparison page is not a source here."""
    for row in evidence:
        host = urlsplit(row.url).hostname or ""
        if row.field == field and row.excerpt.strip() and registrable_domain(host) == domain:
            return row
    return None


def _fact(value: Any, row: Evidence, note: str | None = None, inferred: bool = False) -> Fact:
    return Fact(status="present", value=value, source_url=row.url, source_type="vendor", checked=row.checked, note=note, inferred=inferred)


def _price(candidate: Candidate, domain: str) -> dict[str, Fact]:
    """Only a USD monthly plan becomes a price. Anything else is described in a note and left unknown, never converted."""
    pricing = candidate.pricing
    link = candidate.pricing_url if candidate.pricing_url and registrable_domain(urlsplit(candidate.pricing_url).hostname or "") == domain else None
    price_rows = {r.url: r for r in candidate.evidence if r.field == "pricing.plan" and r.excerpt.strip()}
    monthly = [
        p for p in pricing.plans
        if p.currency == "USD" and p.billing == "monthly" and p.source_url in price_rows
        and registrable_domain(urlsplit(p.source_url).hostname or "") == domain
    ]
    if monthly:
        entry = min(monthly, key=lambda p: p.amount)
        row = price_rows[entry.source_url]
        several = len(monthly) > 1
        note = "Lowest listed monthly plan, inferred by discovery to be the entry price." if several else "Listed monthly plan, read by discovery."
        fields = {"entry_monthly_usd": _fact(entry.amount, row, note, inferred=several)}
        if entry.name and not several:
            fields["entry_plan"] = _fact(entry.name, row)
        return fields
    found = [f"{p.amount:g} {p.currency or 'in an unstated currency'} per {p.unit} ({p.billing})" for p in pricing.plans]
    found += [f"{u.amount:g} {u.currency or 'in an unstated currency'} per {u.per}" for u in pricing.usage_charges]
    if found:
        note = "Listed as " + "; ".join(found) + ". Not a US dollar monthly price, so it was not converted."
    elif pricing.state == "quote_only":
        note = "The vendor asks you to contact them for a price."
    else:
        note = "Discovery could not read a price."
    return {"entry_monthly_usd": Fact(status="unknown", note=note + " Check the vendor's pricing page.", source_url=link)}


def to_tool(catalog: Catalog, request: DiscoveryRequest, candidate: Candidate, checked: date, allow_reserved: bool) -> Tool | str:
    """Returns a pending tool, or the reason the candidate can't be stored."""
    unsafe = public_url(candidate.product_url, allow_reserved)
    if unsafe:
        return f"product link is unsafe ({unsafe})"
    domain = registrable_domain(urlsplit(candidate.product_url).hostname or "")
    if candidate.vendor_domain.casefold() != domain:
        return "vendor domain does not match the product link"
    if candidate.compatibility == "incompatible" or request.capability in candidate.not_offered:
        return "the vendor says it does not do this task"
    known_caps = {c for category in catalog.categories for c in category.capabilities}
    facets = {f.id: f for f in catalog.facets}
    capabilities = []
    for name in dict.fromkeys(candidate.capabilities):
        row = _sourced(candidate.evidence, f"capability.{name}", domain)
        if name not in known_caps or name in candidate.not_offered or row is None:
            continue
        cap_facets = {}
        for facet_id, values in candidate.facets.items():
            facet = facets.get(facet_id)
            if facet is None or name not in facet.capabilities:
                continue
            backed = [v for v in dict.fromkeys(values) if v in facet.values and _sourced(candidate.evidence, f"facet.{facet_id}.{v}", domain)]
            if backed:
                cap_facets[facet_id] = _fact(backed, _sourced(candidate.evidence, f"facet.{facet_id}.{backed[0]}", domain), "Read from the vendor's page by discovery.")
        capabilities.append(Capability(
            capability=name,
            access=Fact(status="unknown", note="Discovery found the feature but not which plan includes it."),
            facets=cap_facets,
        ))
    if not any(c.capability == request.capability for c in capabilities):
        return "no page on the vendor's own site says it does this task"
    trade_ids = {t.id for t in catalog.trades}
    trade_rows = [(t, _sourced(candidate.evidence, f"trade.{t}", domain)) for t in dict.fromkeys(candidate.applicability_trades)]
    trades = [t for t, row in trade_rows if t in trade_ids and row]
    first_trade = next((row for t, row in trade_rows if t in trade_ids and row), None)
    applicability = candidate.applicability if first_trade else "unknown"
    return Tool(
        id=slug(f"{domain}-{candidate.product}"),
        name=candidate.product.strip(),
        url=candidate.product_url,
        trades=trades,
        applicability=applicability,
        applicability_source=first_trade.url if first_trade else None,
        status="pending_review",
        origin="discovered",
        summary=f"Found by discovery on {checked.isoformat()}. Not reviewed yet.",
        capabilities=capabilities,
        **_price(candidate, domain),
    )


def store(conn: sqlite3.Connection, catalog: Catalog, request: DiscoveryRequest, result: FinderResult, today: date,
          allow_reserved: bool = False) -> DiscoveryReport:
    """Saves new candidates as pending tools. A candidate that matches a reviewed catalog tool is reported, not stored."""
    report = DiscoveryReport(run_id=result.run_id[:64] or uuid.uuid4().hex, status=result.status, error=result.error)
    if result.status == "failed":
        return report
    catalog_ids = {t.id for t in catalog.tools if t.origin == "catalog"}
    reviewed = {identity(t): t.id for t in catalog.tools if t.origin == "catalog"}
    discovered = {t.id for t in catalog.tools if t.origin == "discovered"}
    seen: set[str] = set()
    for candidate in result.candidates:
        try:
            made = to_tool(catalog, request, candidate, today, allow_reserved)
            if not isinstance(made, str):
                Catalog(trades=catalog.trades, categories=catalog.categories, problem_cards=[], tools=[made], facets=catalog.facets)
        except ValidationError as exc:
            made = f"its details don't fit the catalog ({exc.errors()[0]['msg'][:120]})"
        if isinstance(made, str):
            report.excluded.append(Skipped(candidate_id=candidate.candidate_id, reason=made))
            continue
        twin = reviewed.get(identity(made)) or (made.id if made.id in catalog_ids else None)
        if twin:
            report.duplicates.append(Skipped(candidate_id=candidate.candidate_id, tool_id=twin, reason="already in the reviewed catalog"))
            continue
        if made.id in seen:
            report.duplicates.append(Skipped(candidate_id=candidate.candidate_id, tool_id=made.id, reason="listed twice in this run"))
            continue
        seen.add(made.id)
        db.add_discovered_tool(conn, made)
        (report.updated if made.id in discovered else report.added).append(made.id)
    return report


def discover(conn: sqlite3.Connection, catalog: Catalog, request: DiscoveryRequest, finder: Finder, today: date,
             allow_fixture: bool = False) -> DiscoveryReport:
    """One call for scripts and the future MCP action. The API route splits it so the slow part runs outside the write lock."""
    try:
        result = run_finder(catalog, request, finder, allow_fixture)
    except DiscoveryFailed as exc:
        return DiscoveryReport(run_id=uuid.uuid4().hex, status="failed", error=ErrorInfo(code=exc.code, message=exc.message[:300]))
    return store(conn, catalog, request, result, today, allow_reserved=allow_fixture)
