import os
import threading
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from . import access, adoption, db
from .comparison import AssignmentError, compare
from .facts import tool_facts
from .matching import check_stack, recommend
from .tasks import resolve_task
from .schemas import (
    AdoptionPlan,
    BusinessProfile,
    Catalog,
    Category,
    Comparison,
    OwnerSession,
    PlanSummary,
    ProblemCard,
    Recommendation,
    SavedPlan,
    Selection,
    StackCheck,
    TaskMatch,
    Tool,
    ToolFact,
    Trade,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


class RecommendRequest(BaseModel):
    profile: BusinessProfile
    problem_id: str


class StackRequest(BaseModel):
    tool_ids: list[str]


class CompareRequest(Selection):
    pass


class PlanRequest(Selection):
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{8,100}$")


class TaskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=300, pattern=r"\S")


@asynccontextmanager
async def lifespan(app: FastAPI):
    catalog_path = Path(os.environ.get("CATALOG_PATH", BACKEND_DIR / "data" / "catalog.json"))
    db_path = Path(os.environ.get("APP_DB_PATH", BACKEND_DIR / "data" / "app.db"))
    catalog = db.load_catalog_file(catalog_path)
    conn = db.connect(db_path)
    try:
        db.seed(conn, catalog)
        app.state.catalog = db.read_catalog(conn)
        app.state.conn = conn
        app.state.lock = threading.Lock()
        yield
    finally:
        conn.close()


app = FastAPI(title="Main Street AI", lifespan=lifespan)


def _catalog(request: Request) -> Catalog:
    return request.app.state.catalog


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _private_enabled() -> None:
    """Set PRIVATE_PLANS=off to close every private route, for example on a host without HTTPS."""
    if os.environ.get("PRIVATE_PLANS", "on").casefold() == "off":
        raise HTTPException(status_code=503, detail="Saving private plans is turned off on this server")


def _owner(request: Request, authorization: str | None = Header(default=None)) -> str:
    _private_enabled()
    with request.app.state.lock:
        try:
            return access.owner_for(request.app.state.conn, access.bearer(authorization), _now())
        except access.AccessDenied as exc:
            raise HTTPException(status_code=401, detail=exc.args[0], headers={"WWW-Authenticate": "Bearer"}) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/trades")
def trades(request: Request) -> list[Trade]:
    return _catalog(request).trades


@app.get("/api/categories")
def categories(request: Request) -> list[Category]:
    return _catalog(request).categories


@app.get("/api/problems")
def problems(request: Request, trade: str | None = None, category: str | None = None) -> list[ProblemCard]:
    catalog = _catalog(request)
    known_trade = catalog.resolve_trade(trade)
    cards = [c for c in catalog.problem_cards if category is None or catalog.category_of(c.capability) == category]
    return sorted(cards, key=lambda card: not card.common_for(known_trade))


@app.get("/api/tools")
def tools(request: Request, trade: str | None = None, capability: str | None = None, category: str | None = None) -> list[Tool]:
    """Business type only orders the directory. Hiding tools here made unlisted businesses see an empty page."""
    catalog = _catalog(request)
    known_trade = catalog.resolve_trade(trade)
    wanted = next((c.capabilities for c in catalog.categories if c.id == category), None) if category else None
    if category and wanted is None:
        raise HTTPException(status_code=404, detail=f"unknown category: {category}")
    found = [
        tool
        for tool in catalog.tools
        if tool.status != "rejected"
        and (capability is None or tool.capability(capability))
        and (wanted is None or any(tool.capability(c) for c in wanted))
    ]
    order = {"made_for": 0, "any_business": 1, "unconfirmed": 2, None: 3}
    return sorted(found, key=lambda tool: order[tool.fit(known_trade)])


@app.get("/api/tools/{tool_id}")
def tool_detail(request: Request, tool_id: str) -> Tool:
    try:
        return _catalog(request).tool(tool_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@app.get("/api/tools/{tool_id}/facts")
def tool_fact_list(request: Request, tool_id: str) -> list[ToolFact]:
    """Cards and the comparison read the same fact wording from here, so a price or source can't be phrased two ways."""
    try:
        return tool_facts(_catalog(request).tool(tool_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@app.post("/api/recommend")
def recommend_route(request: Request, body: RecommendRequest) -> Recommendation:
    catalog = _catalog(request)
    try:
        return recommend(catalog, body.profile, catalog.problem(body.problem_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@app.post("/api/stack/check")
def stack_check(request: Request, body: StackRequest) -> StackCheck:
    try:
        return check_stack(_catalog(request), body.tool_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@app.post("/api/compare")
def compare_route(request: Request, body: CompareRequest) -> Comparison:
    """Uses the same task, business, ownership and plan context as /api/recommend, so prices match the cards."""
    catalog = _catalog(request)
    try:
        return compare(catalog, body.profile, body.problem_ids, body.tool_ids, body.assignments)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    except AssignmentError as exc:
        raise HTTPException(status_code=422, detail=exc.args[0]) from exc


@app.post("/api/tasks/resolve")
def resolve_task_route(request: Request, body: TaskRequest) -> TaskMatch:
    """Free text is matched only against catalog phrases, so the agent and the search box land on the same problem cards."""
    return resolve_task(_catalog(request), body.text)


@app.post("/api/sessions", status_code=201)
def start_session(request: Request) -> OwnerSession:
    """No account is made. The token is shown once and is the only way back into the plans saved under it."""
    _private_enabled()
    with request.app.state.lock:
        token, expires = access.create_session(request.app.state.conn, _now())
    return OwnerSession(token=token, expires_at=expires)


@app.delete("/api/sessions/current", status_code=204)
def end_session(request: Request, owner: str = Depends(_owner)) -> Response:
    with request.app.state.lock:
        access.revoke(request.app.state.conn, owner, _now())
    return Response(status_code=204)


@app.get("/api/plans")
def plan_list(request: Request, owner: str = Depends(_owner)) -> list[PlanSummary]:
    with request.app.state.lock:
        return adoption.list_plans(request.app.state.conn, owner)


@app.post("/api/plans", status_code=201)
def plan_save(request: Request, response: Response, body: PlanRequest, owner: str = Depends(_owner)) -> AdoptionPlan:
    """Answers only after the row is written. A repeat of the same request_id returns the first plan with 200."""
    selection = Selection.model_validate(body.model_dump(exclude={"request_id"}))
    with request.app.state.lock:
        try:
            plan, created = adoption.save_plan(request.app.state.conn, _catalog(request), owner, body.request_id, selection, _now())
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=exc.args[0]) from exc
        except AssignmentError as exc:
            raise HTTPException(status_code=422, detail=exc.args[0]) from exc
        except (adoption.PlanNotReady, adoption.PlanConflict, adoption.PlanLimit) as exc:
            raise HTTPException(status_code=409, detail=exc.args[0]) from exc
    if not created:
        response.status_code = 200
    return plan


@app.get("/api/plans/{plan_id}")
def plan_read(request: Request, plan_id: str, owner: str = Depends(_owner)) -> SavedPlan:
    with request.app.state.lock:
        try:
            plan = adoption.load_plan(request.app.state.conn, owner, plan_id)
        except adoption.PlanNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.args[0]) from exc
    return adoption.check_plan(_catalog(request), plan)


@app.post("/api/plans/{plan_id}/refresh")
def plan_refresh(request: Request, plan_id: str, owner: str = Depends(_owner)) -> AdoptionPlan:
    with request.app.state.lock:
        try:
            return adoption.refresh_plan(request.app.state.conn, _catalog(request), owner, plan_id, _now())
        except adoption.PlanNotFound as exc:
            raise HTTPException(status_code=404, detail=exc.args[0]) from exc
        except KeyError as exc:
            raise HTTPException(status_code=409, detail=f"This plan can't be rebuilt from today's catalog: {exc.args[0]}") from exc
        except (adoption.PlanNotReady, AssignmentError) as exc:
            raise HTTPException(status_code=409, detail=exc.args[0]) from exc
