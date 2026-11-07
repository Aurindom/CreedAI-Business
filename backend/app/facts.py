from .schemas import Fact, Tool, ToolFact

NOT_CHECKED = "Not checked yet"
UNKNOWN = "Unknown"
LEVEL_WORDS = {"low": "Low effort", "medium": "Some effort", "high": "High effort", "strong": "Strong", "partial": "Partial", "weak": "Weak"}


def _from_fact(label: str, fact: Fact, text: str | None = None) -> ToolFact:
    """A note on an unknown fact means someone looked and could not confirm it, which owners should see apart from never checked."""
    if not fact.known:
        if fact.note:
            return ToolFact(label=label, known=False, state="unresolved", value=UNKNOWN, note=fact.note, source_url=fact.source_url, checked=fact.checked)
        return ToolFact(label=label, known=False, state="not_checked", value=NOT_CHECKED)
    return ToolFact(
        label=label,
        known=True,
        state="known",
        value=text or LEVEL_WORDS.get(str(fact.value), str(fact.value)),
        note=fact.note,
        source_url=fact.source_url,
        source_type=fact.source_type,
        checked=fact.checked,
    )


def _price_text(tool: Tool) -> str | None:
    if not tool.entry_monthly_usd.known:
        return None
    price = float(tool.entry_monthly_usd.value)
    parts = ["Free" if price == 0 else f"${price:g}/mo"]
    if tool.entry_plan.known:
        parts.append(f"{tool.entry_plan.value} plan")
    if price and tool.entry_billing.known and tool.entry_billing.value == "annual":
        parts.append("billed annually")
    return ", ".join(parts)


def tool_facts(tool: Tool) -> list[ToolFact]:
    """Facts are shown as they are instead of being blended into a score, so an unknown stays visibly unknown."""
    return [
        _from_fact("Entry price", tool.entry_monthly_usd, _price_text(tool)),
        _from_fact("Setup", tool.setup_effort),
        _from_fact("Privacy", tool.privacy),
        _from_fact("Support", tool.support_stability),
    ]
