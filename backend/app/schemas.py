from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

FactStatus = Literal["present", "absent", "unknown"]
SourceType = Literal["vendor", "third_party"]
Access = Literal["included", "add_on", "unknown"]
ToolStatus = Literal["verified", "pending_review", "rejected"]
Route = Literal["already_have", "check_plan", "native_add_on", "plan_upgrade", "compatible_tool", "separate_tool", "switch"]
Outcome = Literal["no_new_tool", "add_on", "new_tool", "verify_with_vendor", "no_match"]
Applicability = Literal["cross_industry", "restricted", "unknown"]
Fit = Literal["you_use_it", "made_for", "any_business", "unconfirmed"]
FactState = Literal["known", "not_checked", "unresolved"]
ANY_BUSINESS = "all"
MAX_COMPARED = 3
MAX_TASKS = 5


class Fact(BaseModel):
    status: FactStatus
    value: Any = None
    source_url: HttpUrl | None = None
    source_type: SourceType | None = None
    checked: date | None = None
    note: str | None = None

    @model_validator(mode="after")
    def enforce_evidence(self) -> "Fact":
        if self.status == "unknown":
            if self.value is not None:
                raise ValueError("an unknown fact cannot carry a value")
            return self
        if not (self.source_url and self.source_type and self.checked):
            raise ValueError("a known fact needs a source link, source type and date checked")
        return self

    @property
    def known(self) -> bool:
        return self.status == "present" and self.value is not None


UNKNOWN = Fact(status="unknown")


class Capability(BaseModel):
    capability: str
    access: Fact
    addon_monthly_usd: Fact = UNKNOWN
    included_from: Fact = UNKNOWN
    addon_from: Fact = UNKNOWN
    facets: dict[str, Fact] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_access(self) -> "Capability":
        if self.access.known and self.access.value not in ("included", "add_on"):
            raise ValueError(f"bad access value: {self.access.value}")
        if self.included_from.known and self.level != "included":
            raise ValueError(f"{self.capability} names a plan but is not marked included")
        if self.addon_from.known and self.level != "add_on":
            raise ValueError(f"{self.capability} names an add-on plan but is not marked add_on")
        return self

    @property
    def level(self) -> Access:
        return self.access.value if self.access.known else "unknown"


class Tool(BaseModel):
    id: str
    name: str
    url: HttpUrl
    trades: list[str]
    applicability: Applicability = "unknown"
    applicability_source: HttpUrl | None = None
    status: ToolStatus = "pending_review"
    summary: str
    entry_monthly_usd: Fact = UNKNOWN
    entry_plan: Fact = UNKNOWN
    entry_billing: Fact = UNKNOWN
    plan_tiers: Fact = UNKNOWN
    plan_prices: Fact = UNKNOWN
    offering: Fact = UNKNOWN
    setup_effort: Fact = UNKNOWN
    privacy: Fact = UNKNOWN
    support_stability: Fact = UNKNOWN
    connects_to: Fact = UNKNOWN
    capabilities: list[Capability] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_plans(self) -> "Tool":
        """Tier prices share entry_billing's basis and must name sourced tiers, so a price can never float free of its plan."""
        if self.offering.known and self.offering.value not in ("single", "tiered"):
            raise ValueError(f"{self.id}: bad offering value: {self.offering.value}")
        if self.single_offering and self.plan_tiers.known:
            raise ValueError(f"{self.id}: a single offering cannot list plan tiers")
        if self.plan_tiers.known:
            tiers = {str(t).strip().casefold() for t in self.plan_tiers.value}
            named = [("entry_plan", self.entry_plan)]
            named += [(f"{c.capability} plan", f) for c in self.capabilities for f in (c.included_from, c.addon_from)]
            for where, plan in named:
                if plan.known and str(plan.value).strip().casefold() not in tiers:
                    raise ValueError(f"{self.id}: {where} {plan.value} is not in plan_tiers")
        if self.plan_prices.known:
            prices = self.plan_prices.value
            if not isinstance(prices, dict) or not self.plan_tiers.known:
                raise ValueError(f"{self.id}: plan_prices must map sourced plan_tiers to monthly prices")
            tiers = {str(t).casefold() for t in self.plan_tiers.value}
            for name, price in prices.items():
                if str(name).casefold() not in tiers:
                    raise ValueError(f"{self.id}: priced plan {name} is not in plan_tiers")
                if isinstance(price, bool) or not isinstance(price, (int, float)) or price < 0:
                    raise ValueError(f"{self.id}: bad price for plan {name}: {price}")
        return self

    @property
    def single_offering(self) -> bool:
        return self.offering.known and self.offering.value == "single"

    def plan_price(self, plan: str) -> Fact:
        """The entry plan's own fact wins; other tiers come from plan_prices. Anything else stays unknown."""
        if self.entry_plan.known and str(self.entry_plan.value).strip().casefold() == plan.strip().casefold():
            return self.entry_monthly_usd
        if self.plan_prices.known:
            for name, price in self.plan_prices.value.items():
                if str(name).strip().casefold() == plan.strip().casefold():
                    return self.plan_prices.model_copy(update={"value": price})
        return Fact(status="unknown", note=f"Price of the {plan} plan not recorded. Verify with the vendor")

    def capability(self, name: str) -> Capability | None:
        return next((c for c in self.capabilities if c.capability == name), None)

    def fit(self, trade: str | None) -> Fit | None:
        """None means the vendor aims this tool at other kinds of business, so it is set aside."""
        if self.applicability == "cross_industry":
            return "any_business"
        if self.applicability == "unknown" or trade is None:
            return "unconfirmed"
        return "made_for" if trade in self.trades else None

    def plan_rank(self, plan: str | None) -> int | None:
        if not plan or not self.plan_tiers.known:
            return None
        names = [str(p).casefold() for p in self.plan_tiers.value]
        wanted = plan.strip().casefold()
        return names.index(wanted) if wanted in names else None


class Trade(BaseModel):
    id: str
    name: str


class Category(BaseModel):
    id: str
    name: str
    capabilities: list[str]
    labels: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_labels(self) -> "Category":
        stray = set(self.labels) - set(self.capabilities)
        if stray:
            raise ValueError(f"{self.id} labels capabilities it does not hold: {sorted(stray)}")
        return self


class Facet(BaseModel):
    """A way one capability splits, like the channel a lead arrives on. Values map an id to plain words."""
    id: str
    label: str
    capabilities: list[str]
    values: dict[str, str]

    def describe(self, value: str) -> str:
        return self.values.get(value, value)


class ProblemCard(BaseModel):
    id: str
    title: str
    plain_words: str
    capability: str
    trades: list[str]
    requires: dict[str, str] = Field(default_factory=dict)
    phrases: list[str] = Field(default_factory=list)

    def common_for(self, trade: str | None) -> bool:
        return ANY_BUSINESS in self.trades or trade in self.trades


class Catalog(BaseModel):
    trades: list[Trade]
    categories: list[Category]
    problem_cards: list[ProblemCard]
    tools: list[Tool]
    facets: list[Facet] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_references(self) -> "Catalog":
        trade_ids = {t.id for t in self.trades}
        if ANY_BUSINESS in trade_ids:
            raise ValueError(f"'{ANY_BUSINESS}' is reserved and cannot be a business type")
        for item in [*self.problem_cards, *self.tools]:
            missing = set(item.trades) - trade_ids - {ANY_BUSINESS}
            if missing:
                raise ValueError(f"{item.id} names unknown trades: {sorted(missing)}")
        for tool in self.tools:
            if tool.applicability != "unknown" and tool.applicability_source is None:
                raise ValueError(f"{tool.id} states who it is for without a source")
            if tool.applicability == "restricted" and not tool.trades:
                raise ValueError(f"{tool.id} is restricted but lists no business types")
        homes: dict[str, str] = {}
        for category in self.categories:
            for capability in category.capabilities:
                if capability in homes:
                    raise ValueError(f"{capability} is in both {homes[capability]} and {category.id}")
                homes[capability] = category.id
        for card in self.problem_cards:
            if card.capability not in homes:
                raise ValueError(f"{card.id} has no category for {card.capability}")
        self._check_facets(homes)
        for name, ids in [("tool", [t.id for t in self.tools]), ("category", [c.id for c in self.categories])]:
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} ids in catalog")
        return self

    def _check_facets(self, homes: dict[str, str]) -> None:
        """Every split is declared once and every tool or card that uses it is checked the same way."""
        facets: dict[str, Facet] = {}
        for facet in self.facets:
            if facet.id in facets:
                raise ValueError(f"duplicate facet id {facet.id}")
            if not facet.values:
                raise ValueError(f"facet {facet.id} has no values")
            for capability in facet.capabilities:
                if capability not in homes:
                    raise ValueError(f"facet {facet.id} names {capability}, which has no category")
            facets[facet.id] = facet

        def check(where: str, capability: str, facet_id: str, values: list) -> None:
            facet = facets.get(facet_id)
            if facet is None:
                raise ValueError(f"{where} uses unknown facet {facet_id}")
            if capability not in facet.capabilities:
                raise ValueError(f"{where}: facet {facet_id} does not apply to {capability}")
            bad = [v for v in values if v not in facet.values]
            if bad:
                raise ValueError(f"{where}: {facet_id} has unknown values {bad}")

        for card in self.problem_cards:
            for facet_id, value in card.requires.items():
                check(card.id, card.capability, facet_id, [value])
        for tool in self.tools:
            for cap in tool.capabilities:
                for facet_id, f in cap.facets.items():
                    if f.known and (not isinstance(f.value, list) or not f.value):
                        raise ValueError(f"{tool.id} {cap.capability}: {facet_id} must list at least one value")
                    check(f"{tool.id} {cap.capability}", cap.capability, facet_id, f.value if f.known else [])

    def facet(self, facet_id: str) -> Facet:
        return next(f for f in self.facets if f.id == facet_id)

    def capability_label(self, capability: str) -> str:
        """Owners read plain words, so a missing label falls back to the id with its underscores spaced out."""
        for category in self.categories:
            if capability in category.labels:
                return category.labels[capability]
        return capability.replace("_", " ")

    def category_of(self, capability: str) -> str | None:
        return next((c.id for c in self.categories if capability in c.capabilities), None)

    def trade_names(self, ids: list[str], limit: int = 4) -> str:
        names = [t.name for t in self.trades if t.id in ids]
        if len(names) > limit:
            return f"{', '.join(names[:limit])} and {len(names) - limit} more"
        return ", ".join(names)

    def resolve_trade(self, text: str | None) -> str | None:
        wanted = (text or "").strip().casefold().replace(" ", "_")
        for trade in self.trades:
            if wanted in (trade.id, trade.name.casefold().replace(" ", "_")):
                return trade.id
        return None

    def tool(self, tool_id: str) -> Tool:
        for tool in self.tools:
            if tool.id == tool_id:
                return tool
        raise KeyError(f"unknown tool: {tool_id}")

    def problem(self, problem_id: str) -> ProblemCard:
        for card in self.problem_cards:
            if card.id == problem_id:
                return card
        raise KeyError(f"unknown problem: {problem_id}")


class OwnedSoftware(BaseModel):
    tool_id: str
    plan: str | None = Field(default=None, max_length=100)


class BusinessProfile(BaseModel):
    trade: str | None = Field(default=None, max_length=100)
    owned_tool_ids: list[str] = Field(default_factory=list)
    owned: list[OwnedSoftware] = Field(default_factory=list)
    budget_monthly_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def merge_owned(self) -> "BusinessProfile":
        """Older clients send only owned_tool_ids, so those become owned entries with no plan."""
        listed = {o.tool_id for o in self.owned}
        self.owned += [OwnedSoftware(tool_id=t) for t in self.owned_tool_ids if t not in listed]
        self.owned_tool_ids = [o.tool_id for o in self.owned]
        return self

    def plan_for(self, tool_id: str) -> str | None:
        return next((o.plan for o in self.owned if o.tool_id == tool_id), None)


class ToolFact(BaseModel):
    label: str
    known: bool
    state: FactState
    value: str
    note: str | None = None
    source_url: HttpUrl | None = None
    source_type: SourceType | None = None
    checked: date | None = None


class Option(BaseModel):
    tool_id: str
    tool_name: str
    status: ToolStatus
    route: Route
    fit: Fit
    fit_note: str
    added_monthly_usd: float | None
    cost_note: str
    facts: list[ToolFact]
    within_budget: bool | None = None


class SetAside(BaseModel):
    tool_id: str
    tool_name: str
    status: ToolStatus
    reason: str


class Recommendation(BaseModel):
    problem_id: str
    outcome: Outcome
    winner_tool_id: str | None
    options: list[Option]
    check_first: list[Option] = Field(default_factory=list)
    set_aside: list[SetAside] = Field(default_factory=list)
    message: str
    tailored: bool
    tailoring_note: str | None = None
    budget_note: str | None = None


class StackCheck(BaseModel):
    duplicates: list[str]
    known_monthly_usd: float
    total_monthly_usd: float | None
    unknown_cost_tools: list[str]


Standing = Literal["eligible", "check_first", "set_aside"]
Role = Literal["fills_gap", "alternative", "no_fit"]


class TaskFit(BaseModel):
    problem_id: str
    title: str
    standing: Standing
    reason: str
    route: Route | None = None
    added_monthly_usd: float | None = None
    cost_note: str | None = None


class ComparedTool(BaseModel):
    tool_id: str
    tool_name: str
    status: ToolStatus
    role: Role
    role_note: str
    tasks: list[TaskFit]
    facts: list[ToolFact]


class TaskSlot(BaseModel):
    problem_id: str
    title: str
    tool_ids: list[str]
    kind: Literal["covered", "alternatives", "gap"]
    note: str


class Connection(BaseModel):
    tool_ids: list[str]
    state: Literal["listed", "unverified"]
    listed_by: list[str]
    note: str
    sources: list[HttpUrl] = Field(default_factory=list)


class StackLine(BaseModel):
    tool_id: str
    tool_name: str
    problem_ids: list[str]
    monthly_usd: float | None
    note: str


class StackCost(BaseModel):
    lines: list[StackLine]
    known_monthly_usd: float
    total_monthly_usd: float | None
    unknown_cost_tools: list[str]
    assumptions: list[str]
    within_budget: bool | None = None


class Comparison(BaseModel):
    problem_ids: list[str]
    tools: list[ComparedTool]
    tasks: list[TaskSlot]
    overlaps: list[str]
    connections: list[Connection]
    stack: StackCost | None
    stack_note: str


class TaskMatch(BaseModel):
    status: Literal["matched", "ambiguous", "unsupported"]
    problem_id: str | None = None
    choices: list[ProblemCard] = Field(default_factory=list)
    message: str


class Selection(BaseModel):
    """The tasks and tools an owner picked. Compare and saved plans share it so their limits can't drift apart."""

    profile: BusinessProfile = Field(default_factory=BusinessProfile)
    problem_ids: list[str] = Field(min_length=1, max_length=MAX_TASKS)
    tool_ids: list[str] = Field(min_length=1, max_length=MAX_COMPARED)

    @field_validator("problem_ids", "tool_ids")
    @classmethod
    def no_repeats(cls, ids: list[str]) -> list[str]:
        if len(ids) != len(set(ids)):
            raise ValueError("each id can be chosen only once")
        return ids


class PlanStep(BaseModel):
    tool_id: str
    tool_name: str
    status: ToolStatus
    problem_ids: list[str]
    tasks: list[str]
    reasons: list[str]
    monthly_usd: float | None
    cost_note: str
    setup: ToolFact
    facts: list[ToolFact]
    to_confirm: list[str]
    to_try: list[str]


class AdoptionPlan(BaseModel):
    id: str
    selection: Selection
    created_at: datetime
    refreshed_at: datetime | None = None
    steps: list[PlanStep]
    gaps: list[str]
    connections: list[Connection]
    stack: StackCost
    note: str


class SavedPlan(BaseModel):
    plan: AdoptionPlan
    changed: bool
    change_note: str
    current_total_monthly_usd: float | None = None


class PlanSummary(BaseModel):
    id: str
    created_at: datetime
    refreshed_at: datetime | None
    tool_names: list[str]
    total_monthly_usd: float | None


class OwnerSession(BaseModel):
    token: str
    expires_at: datetime
