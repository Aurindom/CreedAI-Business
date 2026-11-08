"""Validate model selection before emitting any owner-visible factual text."""
from __future__ import annotations

from typing import Literal

from pydantic import Field, ValidationError

from .evidence import EvidencePackage, Strict
from .guard import LeakGuard


class ClaimReference(Strict):
    claim_id: str
    evidence_ids: list[str] = Field(max_length=20)


class GroundedAnswer(Strict):
    package_id: str
    claims: list[ClaimReference] = Field(min_length=1, max_length=30)
    winner_tool_ids: list[str] = Field(default_factory=list, max_length=5)
    followup_id: str | None = None


class ValidatedReply(Strict):
    status: Literal["validated", "fallback", "blocked"]
    text: str
    reason: str | None = None
    claim_ids: list[str] = Field(default_factory=list)


FALLBACK = "I could not validate that answer. You can keep browsing and comparing tools, or try again."
BLOCKED = "That reply was blocked. You can keep browsing and comparing tools."


def extract_json(raw: str) -> str:
    """Accept plain JSON or exactly one outer JSON/unlabelled Markdown fence.

    Never search for braces inside commentary or concatenate multiple blocks.
    Parsing and evidence validation still run on the resulting whole document.
    """
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if len(lines) < 3 or lines[0] not in {"```json", "```"} or lines[-1] != "```":
        raise ValueError("invalid_json_fence")
    body = "\n".join(lines[1:-1]).strip()
    if any(line.strip().startswith("```") for line in lines[1:-1]):
        raise ValueError("multiple_json_fences")
    return body


def default_answer(package: EvidencePackage) -> dict:
    """Deterministic baseline; acceptance tests must also exercise model mistakes."""
    claims = {c.id: c for c in package.claims}
    return GroundedAnswer(package_id=package.package_id,
                          claims=[ClaimReference(claim_id=i, evidence_ids=claims[i].evidence_ids) for i in package.default_claim_ids],
                          winner_tool_ids=package.winner_tool_ids).model_dump()


def validate_answer(raw: str | dict, package: EvidencePackage, guard: LeakGuard | None = None) -> ValidatedReply:
    """No free prose is accepted. References must belong to this exact package.

    This establishes fidelity to supplied records, not truth of vendor pages.
    Call before turning text into W09 TextDelta events; do not stream raw JSON.
    """
    guard = guard or LeakGuard([])

    def safe(text: str, status: str, reason: str | None = None, ids=()):
        if guard.tripped or guard.leaks(text):
            guard.tripped = True
            return ValidatedReply(status="blocked", text="" if guard.leaks(BLOCKED) else BLOCKED, reason="guard_intercepted")
        return ValidatedReply(status=status, text=text, reason=reason, claim_ids=list(ids))

    # Inspect rejected output too: validation failure must not obscure a leak attempt.
    import json
    wire = raw if isinstance(raw, str) else json.dumps(raw)
    if guard.leaks(wire):
        guard.tripped = True
        return safe(BLOCKED, "blocked", "guard_intercepted")
    try:
        answer = GroundedAnswer.model_validate_json(extract_json(raw)) if isinstance(raw, str) else GroundedAnswer.model_validate(raw)
        if answer.package_id != package.package_id:
            raise ValueError("wrong_package")
        if len(set(answer.winner_tool_ids)) != len(answer.winner_tool_ids) or set(answer.winner_tool_ids) != set(package.winner_tool_ids):
            raise ValueError("unsupported_winner")
        by_id = {c.id: c for c in package.claims}
        chosen = [r.claim_id for r in answer.claims]
        if len(set(chosen)) != len(chosen):
            raise ValueError("duplicate_claim")
        if not set(package.required_claim_ids) <= set(chosen):
            raise ValueError("missing_required_context")
        for ref in answer.claims:
            claim = by_id.get(ref.claim_id)
            if claim is None:
                raise ValueError("unsupported_claim")
            if len(set(ref.evidence_ids)) != len(ref.evidence_ids) or set(ref.evidence_ids) != set(claim.evidence_ids):
                raise ValueError("mismatched_evidence")
        for winner in package.winner_tool_ids:
            if not any(by_id[i].tool_id == winner for i in chosen):
                raise ValueError("missing_winner_evidence")
        if answer.followup_id is not None and answer.followup_id not in package.followups:
            raise ValueError("unsupported_followup")
        lines = [by_id[i].text for i in chosen]
        refs = {s.id: s for s in package.sources}
        citations: dict[str, list[str]] = {}
        seen_citations: set[tuple[str, str, str | None]] = set()
        for sid in dict.fromkeys(s for r in answer.claims for s in r.evidence_ids):
            row = refs[sid]
            key = (row.url, row.kind, row.checked)
            if row.url and key not in seen_citations:
                seen_citations.add(key)
                detail = f"[{row.kind}]" + (f" (checked {row.checked})" if row.checked else " (check date not recorded)")
                citations.setdefault(row.url, []).append(detail)
        for url, details in citations.items():
            lines.append(f"Source: {url} " + "; ".join(details))
        if answer.followup_id:
            lines.append(package.followups[answer.followup_id])
        return safe("\n\n".join(lines), "validated", ids=chosen)
    except ValidationError:
        return safe(FALLBACK, 'fallback', 'invalid_schema')
    except KeyError:
        return safe(FALLBACK, 'fallback', 'missing_source')
    except ValueError as exc:
        # Fixed codes only: never return exception data or model-authored text.
        codes = {'wrong_package', 'unsupported_winner', 'duplicate_claim',
                 'missing_required_context', 'unsupported_claim', 'mismatched_evidence',
                 'missing_winner_evidence', 'unsupported_followup',
                 'invalid_json_fence', 'multiple_json_fences'}
        code = exc.args[0] if exc.args and exc.args[0] in codes else 'invalid_json'
        return safe(FALLBACK, 'fallback', code)
