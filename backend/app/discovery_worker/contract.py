from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

CONTRACT_VERSION = "1.1.0"
CONTRACT_DIR = Path(__file__).resolve().parent.parent / "contracts" / "v1"

HARD_CAPS = {
    "max_results": 10,
    "max_pages": 16,
    "time_budget_s": 30.0,
    "max_bytes_per_page": 500_000,
    "max_redirects": 3,
    "max_retries": 1,
}
DEFAULTS = {"max_results": 5, "max_pages": 6, "time_budget_s": 15.0}

Provenance = Literal["fixture", "live", "mixed"]
PriceState = Literal["fixed", "usage_based", "quote_only", "unknown", "extraction_failed"]
Compatibility = Literal["matches", "incompatible", "unconfirmed"]
Applicability = Literal["cross_industry", "restricted", "unknown"]
RunStatus = Literal["completed", "partial", "failed"]
SourceStatus = Literal["ok", "failed", "limit_reached", "skipped"]
PageOutcomeCode = Literal[
    "ok", "blocked", "needs_rendering", "too_large", "timeout", "unsafe_url", "http_error",
    "no_identity", "limit_reached", "cancelled", "fetch_error",
]


class ContractError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


SEMANTIC_MODELS = ("Facet", "ProblemCard", "Capability", "Tool", "TaskFit", "StackCost", "PlanStep", "AdoptionPlan")
SEMANTIC_LITERALS = ("Coverage", "ToolStatus", "Standing")


def semantic_surface(schema_text: str) -> dict[str, dict[str, Any]]:
    """Hash and field list of the app models whose meaning this contract relies on (facets, requires,
    coverage, readiness, add-on offers, plan status). Read by regex from the frozen schemas copy, so a
    changed field in a re-copied file shows up as a changed hash instead of silently drifting."""
    import hashlib
    import re

    out: dict[str, dict[str, Any]] = {}
    for name in SEMANTIC_MODELS:
        m = re.search(rf"^class {name}\b.*?(?=^\S)", schema_text + "\nEND", re.S | re.M)
        if not m:
            raise ContractError("snapshot_incomplete", f"model {name} not found in schemas snapshot")
        body = m.group(0)
        fields = sorted(re.findall(r"^    (\w+)\s*:", body, re.M))
        out[name] = {"sha256": hashlib.sha256(body.strip().encode("utf-8")).hexdigest(), "fields": fields}
    for name in SEMANTIC_LITERALS:
        m = re.search(rf"^{name}\s*=.*$", schema_text, re.M)
        if not m:
            raise ContractError("snapshot_incomplete", f"type {name} not found in schemas snapshot")
        out[name] = {"sha256": hashlib.sha256(m.group(0).strip().encode("utf-8")).hexdigest(), "fields": []}
    return out


def _sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


class Snapshot:
    """Frozen copy of the application's public vocabulary. Capabilities, facets and trades come only from here."""

    def __init__(self, catalog: dict[str, Any], meta: dict[str, Any]):
        self.meta = meta
        self.trades = {t["id"]: t["name"] for t in catalog["trades"]}
        self.capabilities = {c for cat in catalog["categories"] for c in cat["capabilities"]}
        self.facets = {f["id"]: f for f in catalog.get("facets", [])}
        self._phrases: dict[str, set[str]] = {c: {c.replace("_", " ")} for c in self.capabilities}
        # Owner complaints and vendor feature names use different wording. These
        # task aliases are shared across vendors; none grants feature entitlement.
        vendor_terms = {
            'phone_answering': ['ai receptionist','virtual receptionist','call answering','telephone answering'],
            'lead_response': ['lead follow up','automated lead response','lead response'],
            'review_requests': ['request reviews','review invitations','review generation'],
            'review_replies': ['reply to reviews','respond to reviews','responding to reviews','review responses'],
            'job_scheduling': ['field service scheduling','job scheduling','dispatch scheduling','appointment scheduling','client self-scheduling','online booking'],
            'appointment_booking': ['online booking','appointment scheduling','schedule appointments','client self-scheduling'],
            'staff_scheduling': ['employee scheduling','shift scheduling','staff scheduling'],
            'website_chat': ['live chat','website chatbot','ai chatbot'],
        }
        for capability,phrases in vendor_terms.items():
            if capability in self._phrases:
                self._phrases[capability].update(phrases)
        for card in catalog["problem_cards"]:
            for phrase in card.get("phrases", []):
                if len(phrase.split()) >= 2:
                    self._phrases.setdefault(card["capability"], set()).add(phrase.casefold())

    @classmethod
    def load(cls, directory: Path | None = None) -> "Snapshot":
        base = directory or CONTRACT_DIR
        catalog = json.loads((base / "app_catalog_snapshot.json").read_text(encoding="utf-8"))
        meta = json.loads((base / "snapshot.meta.json").read_text(encoding="utf-8"))
        if meta.get("contract_version") != CONTRACT_VERSION:
            raise ContractError(
                "contract_version_mismatch",
                f"snapshot is {meta.get('contract_version')}, code expects {CONTRACT_VERSION}",
            )
        for fname, expected in meta.get("files", {}).items():
            if _sha256_file(base / fname) != expected:
                raise ContractError("snapshot_tampered", f"{fname} does not match its recorded hash")
        recorded = meta.get("semantic_surface")
        if not recorded:
            raise ContractError("snapshot_incomplete", "snapshot meta has no semantic_surface")
        actual = semantic_surface((base / "app_schemas_snapshot.py.txt").read_text(encoding="utf-8"))
        if actual != recorded:
            changed = sorted(k for k in set(actual) | set(recorded) if actual.get(k) != recorded.get(k))
            raise ContractError("snapshot_drift", f"app model surface changed: {', '.join(changed)}")
        return cls(catalog, meta)

    def phrases(self, capability: str) -> list[str]:
        return sorted(self._phrases.get(capability, set()), key=lambda p: (-len(p), p))

    def facet_applies(self, facet_id: str, capability: str) -> bool:
        facet = self.facets.get(facet_id)
        return bool(facet) and capability in facet["capabilities"]

    def facet_values(self, facet_id: str) -> dict[str, str]:
        return self.facets[facet_id]["values"]


class DiscoverInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    capability: str = Field(min_length=1, max_length=64)
    trade: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_\- ]+$")
    facets: dict[str, str] = Field(default_factory=dict)
    max_results: int = DEFAULTS["max_results"]
    max_pages: int = DEFAULTS["max_pages"]
    time_budget_s: float = DEFAULTS["time_budget_s"]

    @field_validator("facets")
    @classmethod
    def facet_size(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 8 or any(len(k) > 64 or len(x) > 64 for k, x in v.items()):
            raise ValueError("facets are too large")
        return v

    @model_validator(mode="after")
    def check_caps(self) -> "DiscoverInput":
        for name in ("max_results", "max_pages", "time_budget_s"):
            value = getattr(self, name)
            if value <= 0:
                raise ValueError(f"{name} must be positive")
            if value > HARD_CAPS[name]:
                raise ValueError(f"{name} {value} exceeds the cap of {HARD_CAPS[name]}")
        return self


def validate_request(raw: Any, snapshot: Snapshot) -> DiscoverInput:
    if not isinstance(raw, dict):
        raise ContractError("invalid_input", "request must be an object")
    try:
        req = DiscoverInput.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"]) or "request"
        raise ContractError("invalid_input", f"{where}: {first['msg']}"[:300]) from None
    if req.capability not in snapshot.capabilities:
        raise ContractError("unknown_capability", f"capability {req.capability!r} is not in contract snapshot {CONTRACT_VERSION}")
    for facet_id, value in req.facets.items():
        if facet_id not in snapshot.facets:
            raise ContractError("unknown_facet", f"facet {facet_id!r} is not in contract snapshot {CONTRACT_VERSION}")
        if not snapshot.facet_applies(facet_id, req.capability):
            raise ContractError("facet_not_applicable", f"facet {facet_id!r} does not apply to {req.capability!r}")
        if value not in snapshot.facet_values(facet_id):
            raise ContractError("unknown_facet_value", f"{facet_id!r} has no value {value!r} in contract snapshot {CONTRACT_VERSION}")
    return req


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
    state: PriceState = "unknown"
    plans: list[PricePlan] = Field(default_factory=list)
    usage_charges: list[UsageCharge] = Field(default_factory=list)
    reason: str | None = None

    @model_validator(mode="after")
    def coherent(self) -> "Pricing":
        if self.state == "fixed" and not self.plans:
            raise ValueError("fixed pricing needs at least one plan")
        if self.state == "usage_based" and (self.plans or not self.usage_charges):
            raise ValueError("usage_based pricing needs usage charges and no plans")
        if self.state in ("unknown", "quote_only", "extraction_failed") and (self.plans or self.usage_charges):
            raise ValueError(f"{self.state} pricing cannot carry amounts")
        return self


class Candidate(BaseModel):
    candidate_id: str
    vendor: str
    vendor_domain: str
    product: str
    product_url: str
    pricing_url: str | None = None
    capabilities: list[str] = Field(default_factory=list)
    facets: dict[str, list[str]] = Field(default_factory=dict)
    not_offered: list[str] = Field(default_factory=list)
    hypotheses: dict[str, str] = Field(default_factory=dict)
    applicability: Applicability = "unknown"
    applicability_trades: list[str] = Field(default_factory=list)
    pricing: Pricing = Field(default_factory=Pricing)
    compatibility: Compatibility = "unconfirmed"
    compatibility_reason: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    unresolved_fields: list[str] = Field(default_factory=list)
    discovery_status: Literal["research_candidate"] = "research_candidate"
    provenance: Provenance
    first_seen: str
    last_seen: str
    seen_count: int = 1


class SourceReport(BaseModel):
    source_id: str
    kind: Literal["fixture", "live"]
    status: SourceStatus
    hits: int = 0
    reason_code: str | None = None
    message: str | None = None


class PageOutcome(BaseModel):
    url: str
    outcome: PageOutcomeCode
    detail: str | None = None


class LimitsUsed(BaseModel):
    pages_fetched: int = 0
    search_requests: int = 0
    abandoned_workers: int = 0
    bytes_fetched: int = 0
    elapsed_s: float = 0.0
    caps: dict[str, float]
    exhausted: str | None = None
    cancelled: bool = False


class ErrorInfo(BaseModel):
    code: str
    message: str = Field(max_length=300)


class DiscoverResult(BaseModel):
    contract_version: str
    run_id: str
    status: RunStatus
    provenance: Provenance
    request: dict[str, Any]
    candidates: list[Candidate] = Field(default_factory=list)
    excluded: list[Candidate] = Field(default_factory=list)
    source_reports: list[SourceReport] = Field(default_factory=list)
    page_outcomes: list[PageOutcome] = Field(default_factory=list)
    limits: LimitsUsed | None = None
    error: ErrorInfo | None = None
    notice: str = "Research candidates only. Nothing here is a verified recommendation."


def failure(code: str, message: str, run_id: str = "none", provenance: str = "fixture") -> dict[str, Any]:
    return DiscoverResult(
        contract_version=CONTRACT_VERSION, run_id=run_id, status="failed", provenance=provenance,
        request={}, error=ErrorInfo(code=code, message=message[:300]),
    ).model_dump(mode="json")


def validate_output(raw: Any, snapshot: Snapshot) -> DiscoverResult:
    """Run at the integration boundary: rejects wrong versions and values the app vocabulary does not know."""
    if not isinstance(raw, dict) or raw.get("contract_version") != CONTRACT_VERSION:
        got = raw.get("contract_version") if isinstance(raw, dict) else type(raw).__name__
        raise ContractError("contract_version_mismatch", f"expected contract_version {CONTRACT_VERSION}, got {got}")
    try:
        result = DiscoverResult.model_validate(raw)
    except ValidationError as exc:
        first = exc.errors()[0]
        raise ContractError("invalid_output", f"{'.'.join(str(p) for p in first['loc'])}: {first['msg']}"[:300]) from None
    for cand in [*result.candidates, *result.excluded]:
        for cap in cand.capabilities:
            if cap not in snapshot.capabilities:
                raise ContractError("unknown_capability", f"{cand.candidate_id}: capability {cap!r} not in snapshot {CONTRACT_VERSION}")
        for facet_id, values in cand.facets.items():
            if facet_id not in snapshot.facets:
                raise ContractError("unknown_facet", f"{cand.candidate_id}: facet {facet_id!r} not in snapshot {CONTRACT_VERSION}")
            bad = [v for v in values if v not in snapshot.facet_values(facet_id)]
            if bad:
                raise ContractError("unknown_facet_value", f"{cand.candidate_id}: {facet_id} values {bad} not in snapshot {CONTRACT_VERSION}")
        for t in cand.applicability_trades:
            if t not in snapshot.trades:
                raise ContractError("unknown_trade", f"{cand.candidate_id}: trade {t!r} not in snapshot {CONTRACT_VERSION}")
    return result


def diff_against_catalog(snapshot: Snapshot, catalog_path: Path) -> list[str]:
    """Compare the frozen vocabulary with a live catalog.json. An empty list means compatible."""
    live = Snapshot(json.loads(catalog_path.read_text(encoding="utf-8")), {})
    problems: list[str] = []
    for label, old, new in (
        ("capability", snapshot.capabilities, live.capabilities),
        ("trade", set(snapshot.trades), set(live.trades)),
        ("facet", set(snapshot.facets), set(live.facets)),
    ):
        for gone in sorted(old - new):
            problems.append(f"{label} {gone!r} is in snapshot {CONTRACT_VERSION} but missing from the live catalog")
        for added in sorted(new - old):
            problems.append(f"{label} {added!r} is new in the live catalog and unknown to snapshot {CONTRACT_VERSION}")
    for fid in sorted(set(snapshot.facets) & set(live.facets)):
        old_v, new_v = set(snapshot.facet_values(fid)), set(live.facet_values(fid))
        for gone in sorted(old_v - new_v):
            problems.append(f"facet {fid} value {gone!r} removed in the live catalog")
        for added in sorted(new_v - old_v):
            problems.append(f"facet {fid} value {added!r} added in the live catalog")
        if set(snapshot.facets[fid]["capabilities"]) != set(live.facets[fid]["capabilities"]):
            problems.append(f"facet {fid} now applies to different capabilities")
    return problems


class CurrencyMismatch(ValueError):
    pass


def sum_amounts(items: list[tuple[float, str | None]]) -> tuple[float, str]:
    """Add prices only when every item has the same known currency. Mixed or unknown currency is refused."""
    if not items:
        raise CurrencyMismatch("nothing to sum")
    currencies = {cur for _, cur in items}
    if None in currencies:
        raise CurrencyMismatch("a price has no stated currency, so it cannot be added")
    if len(currencies) > 1:
        raise CurrencyMismatch(f"prices are in different currencies: {', '.join(sorted(currencies))}")
    return round(sum(a for a, _ in items), 6), currencies.pop()


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")
