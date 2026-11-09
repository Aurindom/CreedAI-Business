import hmac
import logging
import asyncio
import os
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, Field

from . import access, adoption, auth, chat_guard, db, discovery, web, schemas
from .agent import bindings
from .capacity import Capacity
from .chat import ChatMemory, ChatRequest, router as chat_router
from .chat_history import router as chat_history_router
from .favourites import router as favourites_router
from .comparison import AssignmentError, compare
from .facts import tool_facts
from .matching import check_stack, checked_for, recommend
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
        bindings.ensure_schema(conn)
        app.state.catalog = db.read_catalog(conn)
        app.state.conn = conn
        app.state.lock = threading.RLock()
        app.state.history_lock = asyncio.Lock()
        app.state.capacity = Capacity(1)
        app.state.discovery_finder = None
        from . import verification_store, verification_worker
        if verification_worker.enabled():
            verification_store.enqueue(conn, verification_store.source_tools(conn))
        from . import live_discovery
        if live_discovery.enabled():
            app.state.discovery_finder = live_discovery.make_finder(catalog, db_path.with_name('discovery.db'))
        yield
    finally:
        finder = getattr(app.state, 'discovery_finder', None)
        if callable(getattr(finder, 'close', None)):
            finder.close()
        conn.close()


app = FastAPI(title="Main Street AI", lifespan=lifespan)


@app.exception_handler(RequestValidationError)
async def _log_rejected_fields(request: Request, exc: RequestValidationError):
    """Only schema field names are diagnostic data; dict keys and URL values can be private."""
    models = [value for value in vars(schemas).values() if isinstance(value, type) and issubclass(value, BaseModel)]
    models += [ChatRequest, ChatMemory, RecommendRequest, StackRequest, CompareRequest, PlanRequest, TaskRequest]
    allowed = {'body', 'query', 'path', 'header', 'cookie'} | {name for model in models for name in model.model_fields}
    fields = sorted({'.'.join(str(part) if isinstance(part, int) or part in allowed else '<key>'
                             for part in error.get('loc', ())[:8]) for error in exc.errors()})[:20]
    route = getattr(request.scope.get('route'), 'path', '<unmatched>')
    logging.getLogger('app.requests').warning('Rejected %s %s: invalid %s', request.method, route, ', '.join(fields))
    return await request_validation_exception_handler(request, exc)
web.install(app)
app.include_router(chat_router)
app.include_router(chat_history_router)
app.include_router(favourites_router)


@app.middleware('http')
async def private_responses_are_not_cached(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(('/api/auth/', '/api/plans', '/api/chat/history', '/api/favourites')):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Vary'] = 'Authorization'
    return response


def _catalog(request: Request) -> Catalog:
    with request.app.state.lock:
        request.app.state.catalog = db.read_catalog(request.app.state.conn)
        return request.app.state.catalog


def _verification_operator(authorization: str | None = Header(default=None)):
    token = os.environ.get('DISCOVERY_TOKEN', '')
    if len(token) < 24:
        raise HTTPException(503, 'Catalog operations are disabled')
    given = authorization[7:] if authorization and authorization[:7].lower() == 'bearer ' else ''
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, 'Operator authorization required')


@app.get('/api/verification/status')
def verification_status(request: Request):
    from . import verification_store, verification_worker
    with request.app.state.lock:
        return {'enabled': verification_worker.enabled(), **verification_store.status(request.app.state.conn)}


class VerificationSweep(BaseModel):
    tool_id: str | None = Field(default=None, max_length=100)
    force: bool = False


@app.post('/api/verification/sweep', dependencies=[Depends(_verification_operator)])
def verification_sweep(request: Request, body: VerificationSweep):
    from . import verification_store, verification_worker
    if not verification_worker.enabled():
        raise HTTPException(503, 'Catalog verification is disabled')
    with request.app.state.lock:
        tools = verification_store.source_tools(request.app.state.conn)
        if body.tool_id:
            tools = [tool for tool in tools if tool.id == body.tool_id]
            if not tools:
                raise HTTPException(404, 'Tool not found')
        count = verification_store.enqueue(request.app.state.conn, tools, force=body.force)
    return {'queued': count}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _private_enabled() -> None:
    """Set PRIVATE_PLANS=off to close every private route, for example on a host without HTTPS."""
    if os.environ.get("PRIVATE_PLANS", "on").casefold() == "off":
        raise HTTPException(status_code=503, detail="Saving private plans is turned off on this server")


async def _owner(request: Request, principal: auth.Principal = Depends(auth.require_account)) -> str:
    _private_enabled()
    with request.app.state.lock:
        return access.account_owner(request.app.state.conn, principal.user_id, _now())[0]


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


class DirectoryTool(Tool):
    checked_capabilities: list[str] = []


def _directory(tool: Tool) -> DirectoryTool:
    """Browse surfaces show the same per-task verdict as recommendations instead of trusting a product-wide flag."""
    checked = [c.capability for c in tool.capabilities if checked_for(tool, c.capability)]
    return DirectoryTool(**tool.model_dump(), checked_capabilities=checked)


@app.get("/api/tools")
def tools(request: Request, trade: str | None = None, capability: str | None = None, category: str | None = None) -> list[DirectoryTool]:
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
    return [_directory(tool) for tool in sorted(found, key=lambda tool: order[tool.fit(known_trade)])]


@app.get("/api/tools/{tool_id}")
def tool_detail(request: Request, tool_id: str) -> DirectoryTool:
    try:
        return _directory(_catalog(request).tool(tool_id))
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


@app.post("/api/sessions", deprecated=True)
def start_session(request: Request):
    """Deprecated browser-only session creation; account sign-in now owns plans."""
    raise HTTPException(410, 'Sign in to save plans. New browser-only private sessions are no longer created.')


@app.delete("/api/sessions/current", status_code=204)
def end_session(request: Request) -> Response:
    raise HTTPException(410, 'Use account sign out to close this login session.')


@app.get('/api/auth/me')
def account_details(request: Request, principal: auth.Principal = Depends(auth.optional_account)):
    if not principal.authenticated:
        return {'auth_mode': 'guest', 'user_id': None, 'business_id': None}
    with request.app.state.lock:
        _, business = access.account_owner(request.app.state.conn, principal.user_id, _now())
    return {'auth_mode': 'account', 'user_id': principal.user_id, 'business_id': business}


class LegacyClaim(BaseModel):
    legacy_token: str = Field(min_length=20, max_length=200)


@app.post('/api/plans/claim-legacy')
def claim_browser_plans(request: Request, body: LegacyClaim, principal: auth.Principal = Depends(auth.require_account)):
    _private_enabled()
    with request.app.state.lock:
        try:
            count = access.claim_legacy(request.app.state.conn, principal.user_id, body.legacy_token, _now())
        except access.AccessDenied:
            raise HTTPException(401, 'The old private session cannot be claimed') from None
    return {'imported': count}


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


def _discovery_allowed(request: Request, authorization: str | None = Header(default=None)) -> discovery.Finder:
    """Discovery reads the open web, so it stays off unless the operator sets DISCOVERY_TOKEN and wires a finder."""
    token = os.environ.get("DISCOVERY_TOKEN", "")
    finder = getattr(request.app.state, "discovery_finder", None)
    if not token or finder is None:
        raise HTTPException(status_code=503, detail="Tool discovery is turned off on this server")
    given = authorization[7:] if authorization and authorization[:7].casefold() == "bearer " else ""
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(status_code=401, detail="Discovery needs the operator token", headers={"WWW-Authenticate": "Bearer"})
    return finder


@app.post("/api/discover")
def discover_route(request: Request, body: discovery.DiscoveryRequest, finder: discovery.Finder = Depends(_discovery_allowed)) -> discovery.DiscoveryReport:
    from . import verification_store, verification_worker
    if not verification_worker.enabled():
        return _discover_route(request,body,finder)
    try:
        discovery.check_request(_catalog(request),body)
    except discovery.DiscoveryFailed as exc:
        raise HTTPException(422,exc.message) from exc
    with request.app.state.lock:
        claim=verification_store.query_claim(request.app.state.conn,body)
    if claim['state']=='cached':
        return discovery.DiscoveryReport.model_validate(claim['doc'])
    if claim['state']=='busy':
        raise HTTPException(429,'This research task is already running',headers={'Retry-After':'30'})
    report=None
    try:
        report=_discover_route(request,body,finder)
        return report
    finally:
        with request.app.state.lock:
            verification_store.query_finish(request.app.state.conn,claim,report)


def _discover_route(request: Request, body: discovery.DiscoveryRequest, finder: discovery.Finder) -> discovery.DiscoveryReport:
    """Finds new candidate tools for one task. They are saved as pending and show up in /api/tools straight away.

    The slow search runs outside the write lock so browsing keeps working. Only one run happens at a time.
    """
    try:
        discovery.check_request(_catalog(request), body)
    except discovery.DiscoveryFailed as exc:
        raise HTTPException(status_code=422, detail=exc.message) from exc
    claim = request.app.state.capacity.try_claim()
    if claim is None:
        raise HTTPException(status_code=429, detail="A discovery run is already going or still stopping. Try again when it finishes")
    try:
        result = discovery.run_finder(_catalog(request), body, finder, claim=claim)
    except discovery.DiscoveryFailed as exc:
        return discovery.DiscoveryReport(run_id=uuid.uuid4().hex, status="failed", error=discovery.ErrorInfo(code=exc.code, message=exc.message))
    with request.app.state.lock:
        report = discovery.store(request.app.state.conn, _catalog(request), body, result, _now().date())
        from . import verification_store, verification_worker
        if verification_worker.enabled():
            verification_store.enqueue(request.app.state.conn, verification_store.source_tools(request.app.state.conn))
        request.app.state.catalog = db.read_catalog(request.app.state.conn)
    if not verification_worker.enabled() and callable(getattr(finder, 'review', None)) and os.environ.get('DISCOVERY_AUTO_VERIFY', '').lower() in ('1', 'true', 'yes'):
        from . import auto_verification
        for tool_id in (report.added + report.updated)[:3]:
            try:
                current = _catalog(request)
                checked = finder.review(current.tool(tool_id), body.capability, current)
                with request.app.state.lock:
                    auto_verification.save(request.app.state.conn, checked)
                    request.app.state.catalog = db.read_catalog(request.app.state.conn)
                report.automatically_checked.append(tool_id)
                if checked.auto_review and checked.auto_review.eligible:
                    report.promoted.append(tool_id)
                report.verification_notes[tool_id] = checked.auto_review.notes if checked.auto_review else []
            except Exception as exc:
                import logging
                logging.getLogger(__name__).warning('Automatic review did not finish: %s', type(exc).__name__)
                report.verification_notes[tool_id] = ['Automatic checks could not finish. Existing evidence is retained.']
                from .schemas import AutomaticReview
                with request.app.state.lock:
                    original = _catalog(request).tool(tool_id)
                    failed = original.model_copy(update={'status': 'pending_review', 'auto_review': AutomaticReview(
                        checked=_now().date(), capability=body.capability, checks={'verification_completed': False},
                        notes=report.verification_notes[tool_id], sources=[])})
                    auto_verification.save(request.app.state.conn, failed)
                    request.app.state.catalog = db.read_catalog(request.app.state.conn)
    if callable(getattr(finder, 'update_catalog', None)):
        finder.update_catalog(_catalog(request))
    return report


@app.get('/api/discovery/status')
def discovery_status(request: Request):
    finder = getattr(request.app.state, 'discovery_finder', None)
    available = (os.environ.get('DISCOVERY_PUBLIC_ENABLED', '').lower() in ('1', 'true', 'yes') and finder is not None)
    if available and callable(getattr(finder, 'available', None)):
        try:
            available = finder.available()
        except (OSError, sqlite3.Error):
            available = False
    return {'available': available}


@app.post('/api/research')
def public_research(request: Request, body: discovery.DiscoveryRequest):
    """Bounded public research; operator credentials never leave the backend."""
    if not discovery_status(request)['available']:
        raise HTTPException(503, 'Live research is not enabled')
    try:
        discovery.check_request(_catalog(request), body)
    except discovery.DiscoveryFailed as exc:
        raise HTTPException(422, exc.message) from exc
    import hashlib
    import time
    client = hashlib.sha256(chat_guard.client_id(request).encode()).hexdigest()
    hour = int(time.time() // 3600)
    with request.app.state.lock, request.app.state.conn:
        conn = request.app.state.conn
        conn.execute('CREATE TABLE IF NOT EXISTS research_usage (client TEXT, hour INTEGER, count INTEGER NOT NULL, PRIMARY KEY(client,hour))')
        # Keep the single-worker deployment's public web workload finite and persistent.
        conn.execute('DELETE FROM research_usage WHERE hour < ?', (hour-24,))
        own = conn.execute('SELECT count FROM research_usage WHERE client=? AND hour=?', (client, hour)).fetchone()
        total = conn.execute('SELECT COALESCE(SUM(count),0) FROM research_usage WHERE hour=?', (hour,)).fetchone()[0]
        if (own and own[0] >= 4) or total >= 20:
            raise HTTPException(429, 'Research is busy. Try again later.', headers={'Retry-After': '3600'})
        conn.execute('INSERT INTO research_usage VALUES(?,?,1) ON CONFLICT(client,hour) DO UPDATE SET count=count+1', (client, hour))
    return discover_route(request, body, request.app.state.discovery_finder)
