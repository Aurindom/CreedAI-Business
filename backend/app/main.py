import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import db
from .comparison import MAX_COMPARED, MAX_TASKS, compare
from .facts import tool_facts
from .matching import check_stack, recommend
from .tasks import resolve_task
from .schemas import BusinessProfile, Catalog, Comparison, Category, ProblemCard, Recommendation, StackCheck, TaskMatch, Tool, ToolFact, Trade

BACKEND_DIR = Path(__file__).resolve().parent.parent


class RecommendRequest(BaseModel):
    profile: BusinessProfile
    problem_id: str


class StackRequest(BaseModel):
    tool_ids: list[str]


class CompareRequest(BaseModel):
    profile: BusinessProfile = Field(default_factory=BusinessProfile)
    problem_ids: list[str] = Field(min_length=1, max_length=MAX_TASKS)
    tool_ids: list[str] = Field(min_length=1, max_length=MAX_COMPARED)

    @field_validator("problem_ids", "tool_ids")
    @classmethod
    def no_repeats(cls, ids: list[str]) -> list[str]:
        if len(ids) != len(set(ids)):
            raise ValueError("each id can be chosen only once")
        return ids


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
        yield
    finally:
        conn.close()


app = FastAPI(title="Main Street AI", lifespan=lifespan)


def _catalog(request: Request) -> Catalog:
    return request.app.state.catalog


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
        return compare(catalog, body.profile, body.problem_ids, body.tool_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=exc.args[0]) from exc


@app.post("/api/tasks/resolve")
def resolve_task_route(request: Request, body: TaskRequest) -> TaskMatch:
    """Free text is matched only against catalog phrases, so the agent and the search box land on the same problem cards."""
    return resolve_task(_catalog(request), body.text)
