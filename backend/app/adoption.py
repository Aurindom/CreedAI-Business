import hashlib
import secrets
import sqlite3
from datetime import datetime

from .comparison import compare
from .schemas import AdoptionPlan, Catalog, Comparison, PlanStep, PlanSummary, SavedPlan, Selection

MAX_PLANS = 20
NOTE = "This plan is guidance. Nothing is bought, connected or set up for you."
SNAPSHOT_FIELDS = {"steps", "gaps", "connections", "stack"}


class PlanNotReady(Exception):
    pass


class PlanNotFound(Exception):
    pass


class PlanConflict(Exception):
    pass


class PlanLimit(Exception):
    pass


def _steps(catalog: Catalog, result: Comparison) -> list[PlanStep]:
    compared = {t.tool_id: t for t in result.tools}
    steps = []
    for line in result.stack.lines:
        tool, entry = catalog.tool(line.tool_id), compared[line.tool_id]
        fits = [f for f in entry.tasks if f.problem_id in line.problem_ids]
        setup = next(f for f in entry.facts if f.label == "Setup")
        to_confirm = [f"{f.title}: {f.reason}" for f in fits if f.standing == "check_first"]
        if line.monthly_usd is None:
            to_confirm.append(line.note)
        if tool.entry_billing.known and tool.entry_billing.value == "annual":
            to_confirm.append("It's billed annually, so check the yearly commitment before signing up")
        to_confirm += [c.note for c in result.connections if tool.id in c.tool_ids]
        if not setup.known:
            to_confirm.append("We haven't recorded how much setup it needs. Ask the vendor")
        labels = dict.fromkeys(catalog.capability_label(catalog.problem(p).capability) for p in line.problem_ids)
        steps.append(
            PlanStep(
                tool_id=tool.id,
                tool_name=tool.name,
                status=tool.status,
                problem_ids=line.problem_ids,
                tasks=[f.title for f in fits],
                reasons=[f"{f.title}: {f.reason}" for f in fits],
                monthly_usd=line.monthly_usd,
                cost_note=line.note,
                setup=setup,
                facts=entry.facts,
                to_confirm=to_confirm,
                to_try=[f"Before paying, check that it handles {label} the way your business does it" for label in labels],
            )
        )
    return steps


def build_plan(catalog: Catalog, selection: Selection, plan_id: str, created_at: datetime) -> AdoptionPlan:
    """Built from the same comparison the owner saw, so a saved plan can't quote a price the comparison didn't."""
    result = compare(catalog, selection.profile, selection.problem_ids, selection.tool_ids)
    if result.stack is None:
        raise PlanNotReady(result.stack_note)
    return AdoptionPlan(
        id=plan_id,
        selection=selection,
        created_at=created_at,
        steps=_steps(catalog, result),
        gaps=[s.title for s in result.tasks if s.kind == "gap"],
        connections=result.connections,
        stack=result.stack,
        note=NOTE,
    )


def _request_hash(selection: Selection) -> str:
    return hashlib.sha256(selection.model_dump_json().encode("utf-8")).hexdigest()


def _existing(conn: sqlite3.Connection, owner: str, request_id: str, request_hash: str) -> AdoptionPlan | None:
    row = conn.execute(
        "SELECT request_hash, doc FROM adoption_plan WHERE owner_hash = ? AND request_id = ?", (owner, request_id)
    ).fetchone()
    if row is None:
        return None
    if row[0] != request_hash:
        raise PlanConflict("This confirm id was already used for a different selection")
    return AdoptionPlan.model_validate_json(row[1])


def save_plan(conn: sqlite3.Connection, catalog: Catalog, owner: str, request_id: str, selection: Selection, now: datetime) -> tuple[AdoptionPlan, bool]:
    """A retried or double-clicked confirm carries the same request_id and gets the first plan back instead of a copy."""
    request_hash = _request_hash(selection)
    if found := _existing(conn, owner, request_id, request_hash):
        return found, False
    (count,) = conn.execute("SELECT COUNT(*) FROM adoption_plan WHERE owner_hash = ?", (owner,)).fetchone()
    if count >= MAX_PLANS:
        raise PlanLimit(f"A private session can hold up to {MAX_PLANS} plans")
    plan = build_plan(catalog, selection, secrets.token_urlsafe(12), now)
    try:
        with conn:
            conn.execute(
                "INSERT INTO adoption_plan (id, owner_hash, request_id, request_hash, created_at, doc) VALUES (?, ?, ?, ?, ?, ?)",
                (plan.id, owner, request_id, request_hash, now.isoformat(), plan.model_dump_json()),
            )
    except sqlite3.IntegrityError:
        if found := _existing(conn, owner, request_id, request_hash):
            return found, False
        raise
    return plan, True


def load_plan(conn: sqlite3.Connection, owner: str, plan_id: str) -> AdoptionPlan:
    """Someone else's plan and a missing plan give the same answer, so ids can't be probed."""
    row = conn.execute("SELECT doc FROM adoption_plan WHERE id = ? AND owner_hash = ?", (plan_id, owner)).fetchone()
    if row is None:
        raise PlanNotFound("No such plan in this private session")
    return AdoptionPlan.model_validate_json(row[0])


def list_plans(conn: sqlite3.Connection, owner: str) -> list[PlanSummary]:
    rows = conn.execute("SELECT doc FROM adoption_plan WHERE owner_hash = ? ORDER BY created_at DESC", (owner,)).fetchall()
    plans = [AdoptionPlan.model_validate_json(r[0]) for r in rows]
    return [
        PlanSummary(id=p.id, created_at=p.created_at, refreshed_at=p.refreshed_at, tool_names=[s.tool_name for s in p.steps], total_monthly_usd=p.stack.total_monthly_usd)
        for p in plans
    ]


def check_plan(catalog: Catalog, plan: AdoptionPlan) -> SavedPlan:
    """The saved estimate is shown as saved. Today's catalog only decides whether to offer a refresh."""
    saved_on = (plan.refreshed_at or plan.created_at).date().isoformat()
    try:
        fresh = build_plan(catalog, plan.selection, plan.id, plan.created_at)
    except (KeyError, PlanNotReady) as exc:
        reason = exc.args[0] if exc.args else "the catalog changed"
        return SavedPlan(plan=plan, changed=True, change_note=f"Saved on {saved_on}. It can't be rebuilt from today's catalog: {reason}")
    if fresh.model_dump(include=SNAPSHOT_FIELDS) == plan.model_dump(include=SNAPSHOT_FIELDS):
        return SavedPlan(plan=plan, changed=False, change_note=f"Saved on {saved_on}. Nothing has changed since", current_total_monthly_usd=fresh.stack.total_monthly_usd)
    return SavedPlan(
        plan=plan,
        changed=True,
        change_note=f"Saved on {saved_on}. Prices or facts have changed since. Refresh to update this plan",
        current_total_monthly_usd=fresh.stack.total_monthly_usd,
    )


def refresh_plan(conn: sqlite3.Connection, catalog: Catalog, owner: str, plan_id: str, now: datetime) -> AdoptionPlan:
    """Only an explicit refresh rewrites a saved estimate. The original created_at is kept."""
    plan = load_plan(conn, owner, plan_id)
    fresh = build_plan(catalog, plan.selection, plan.id, plan.created_at).model_copy(update={"refreshed_at": now})
    with conn:
        conn.execute("UPDATE adoption_plan SET doc = ? WHERE id = ? AND owner_hash = ?", (fresh.model_dump_json(), plan_id, owner))
    return fresh
