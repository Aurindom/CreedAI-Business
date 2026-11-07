from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator

FactStatus = Literal["present", "absent", "unknown"]
SourceType = Literal["vendor", "third_party"]
Access = Literal["included", "add_on", "unknown"]
ToolStatus = Literal["verified", "pending_review", "rejected"]
Route = Literal["already_have", "check_plan", "native_add_on", "plan_upgrade", "compatible_tool", "separate_tool", "switch"]
Outcome = Literal["no_new_tool", "add_on", "new_tool", "verify_with_vendor", "no_match"]
Applicability = Literal["cross_industry", "restricted", "unknown"]
Fit = Literal["you_use_it", "made_for", "any_business", "unconfirmed"]
ANY_BUSINESS = "all"


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

    @model_validator(mode="after")
    def check_access(self) -> "Capability":
        if self.access.known and self.access.value not in ("included", "add_on"):
            raise ValueError(f"bad access value: {self.access.value}")
        if self.included_from.known and self.level != "included":
            raise ValueError(f"{self.capability} names a plan but is not marked included")
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
    setup_effort: Fact = UNKNOWN
    privacy: Fact = UNKNOWN
    support_stability: Fact = UNKNOWN
    connects_to: Fact = UNKNOWN
    capabilities: list[Capability] = Field(default_factory=list)

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


class ProblemCard(BaseModel):
    id: str
    title: str
    plain_words: str
    capability: str
    trades: list[str]

    def common_for(self, trade: str | None) -> bool:
        return ANY_BUSINESS in self.trades or trade in self.trades


class Catalog(BaseModel):
    trades: list[Trade]
    categories: list[Category]
    problem_cards: list[ProblemCard]
    tools: list[Tool]

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
        for name, ids in [("tool", [t.id for t in self.tools]), ("category", [c.id for c in self.categories])]:
            if len(ids) != len(set(ids)):
                raise ValueError(f"duplicate {name} ids in catalog")
        return self

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
    value: str
    note: str | None = None
    source_url: HttpUrl | None = None
    source_type: SourceType | None = None
    checked: date | None = None


class Option(BaseModel):
    tool_id: str
    tool_name: str
    route: Route
    fit: Fit
    fit_note: str
    added_monthly_usd: float | None
    cost_note: str
    facts: list[ToolFact]


class SetAside(BaseModel):
    tool_id: str
    tool_name: str
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


class StackCheck(BaseModel):
    duplicates: list[str]
    known_monthly_usd: float
    total_monthly_usd: float | None
    unknown_cost_tools: list[str]
