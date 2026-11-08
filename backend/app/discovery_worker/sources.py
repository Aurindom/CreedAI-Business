from __future__ import annotations

import ipaddress
import json
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit

from .contract import HARD_CAPS


class FetchError(Exception):
    def __init__(self, outcome: str, detail: str = ""):
        super().__init__(detail or outcome)
        self.outcome = outcome
        self.detail = detail


class LimitReached(Exception):
    def __init__(self, which: str):
        super().__init__(which)
        self.which = which


class Cancelled(Exception):
    pass


class TransportTimeout(Exception):
    pass


class TransportError(Exception):
    pass


class WorkTimeout(Exception):
    pass


MAX_ABANDONED_WORKERS = 3
WORK_POLL_S = 0.02


def run_bounded(fn: Callable[[], Any], timeout_s: float, cancel: threading.Event | None = None,
                on_abandon: Callable[[], None] | None = None) -> Any:
    """Run fn on a helper thread and stop waiting at the deadline or on cancel.

    The cancellation guarantee is cooperative for the work and real for the caller. The caller always gets
    control back by the deadline or within about WORK_POLL_S of cancel being set. The helper thread itself
    cannot be killed in Python, so a stalled search call or DNS lookup keeps running in the background until
    its own library timeout. It is a daemon thread, its late result is discarded, and each abandonment is
    counted so a run can stop starting new work after MAX_ABANDONED_WORKERS stalls.
    """
    box: dict[str, Any] = {}
    done = threading.Event()

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=target, daemon=True).start()
    deadline = time.monotonic() + max(0.01, timeout_s)
    while not done.wait(WORK_POLL_S):
        if cancel is not None and cancel.is_set():
            if on_abandon:
                on_abandon()
            raise Cancelled()
        if time.monotonic() >= deadline:
            if on_abandon:
                on_abandon()
            raise WorkTimeout()
    if "error" in box:
        raise box["error"]
    return box["value"]


class Resolver(Protocol):
    def __call__(self, host: str) -> list[str]: ...


def system_resolver(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})
    except OSError as exc:
        raise FetchError("fetch_error", "dns lookup failed") from exc


BLOCKED_SUFFIXES = (".local", ".localhost", ".internal", ".localdomain", ".lan", ".home", ".corp")


@dataclass(frozen=True)
class Resolved:
    """A url whose host was resolved once and checked. The transport must connect to these addresses only."""
    url: str
    host: str
    ips: tuple[str, ...]


def resolve_public(url: str, resolver: Resolver, timeout_s: float = 8.0, cancel: threading.Event | None = None,
                   on_abandon: Callable[[], None] | None = None) -> Resolved:
    """Check a public http(s) destination and return the exact addresses that passed the check."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchError("unsafe_url", "scheme not allowed")
    if parts.username or parts.password:
        raise FetchError("unsafe_url", "credentials in url")
    host = (parts.hostname or "").rstrip(".").casefold()
    if not host:
        raise FetchError("unsafe_url", "missing host")
    try:
        port = parts.port
    except ValueError:
        raise FetchError("unsafe_url", "bad port") from None
    if port not in (None, 80, 443):
        raise FetchError("unsafe_url", "port not allowed")
    if host == "localhost" or host.endswith(BLOCKED_SUFFIXES):
        raise FetchError("unsafe_url", "internal host name")
    addresses = _literal_addresses(host)
    if addresses is None:
        try:
            answers = run_bounded(lambda: resolver(host), timeout_s, cancel, on_abandon)
        except WorkTimeout:
            raise FetchError("timeout", "dns lookup timed out") from None
        try:
            addresses = [ipaddress.ip_address(a.split("%")[0]) for a in answers]
        except ValueError:
            raise FetchError("unsafe_url", "resolver returned a bad address") from None
    if not addresses:
        raise FetchError("unsafe_url", "host did not resolve")
    for addr in addresses:
        mapped = getattr(addr, "ipv4_mapped", None)
        if not (mapped or addr).is_global:
            raise FetchError("unsafe_url", "destination is not a public address")
    return Resolved(url, host, tuple(str(a) for a in addresses))


def guard_url(url: str, resolver: Resolver) -> str:
    """Return the url if it is a public http(s) destination, else raise FetchError('unsafe_url')."""
    return resolve_public(url, resolver).url


def _literal_addresses(host: str):
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        return [ipaddress.ip_address(socket.inet_aton(host))]
    except OSError:
        pass
    if host.isdigit() or host.lower().startswith("0x"):
        raise FetchError("unsafe_url", "numeric host form")
    return None


@dataclass
class Budget:
    max_pages: int
    time_budget_s: float
    max_bytes_per_page: int = HARD_CAPS["max_bytes_per_page"]
    max_redirects: int = HARD_CAPS["max_redirects"]
    max_retries: int = HARD_CAPS["max_retries"]
    clock: Callable[[], float] = time.monotonic
    cancel: threading.Event | None = None
    ledger: "Ledger | None" = None
    pages: int = 0
    searches: int = 0
    abandoned: int = 0
    bytes: int = 0
    exhausted: str | None = None
    started: float = field(init=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    @property
    def elapsed(self) -> float:
        return self.clock() - self.started

    @property
    def remaining(self) -> float:
        return self.time_budget_s - self.elapsed

    def check(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise Cancelled()
        if self.remaining <= 0:
            self._stop("time")

    def charge_page(self) -> None:
        self.check()
        if self.pages >= self.max_pages:
            self._stop("pages")
        if self.ledger is not None and not self.ledger.try_acquire(1):
            self._stop("rate_window")
        self.pages += 1

    def charge_search(self) -> None:
        """A search request is network work, so it spends the same page cap, rolling window and time."""
        self.charge_page()
        self.searches += 1

    def note_abandoned(self) -> None:
        self.abandoned += 1

    def allow_new_worker(self) -> None:
        if self.abandoned >= MAX_ABANDONED_WORKERS:
            self._stop("workers")

    def _stop(self, which: str) -> None:
        self.exhausted = which
        raise LimitReached(which)


class Ledger(Protocol):
    def try_acquire(self, n: int) -> bool: ...


class RawResponse:
    """A response with an explicit lifecycle. close() is idempotent and releases the connection and client."""

    def __init__(self, status: int, headers: dict[str, str], chunks: Iterator[bytes],
                 on_close: Callable[[], None] | None = None):
        self.status = status
        self.headers = headers
        self.chunks = chunks
        self._on_close = on_close
        self.closed = False

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        closer = getattr(self.chunks, "close", None)
        try:
            if closer:
                closer()
        finally:
            if self._on_close:
                self._on_close()

    def __enter__(self) -> "RawResponse":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


class Transport(Protocol):
    kind: str

    def get(self, url: str, timeout: float, pinned_ips: tuple[str, ...] = ()) -> RawResponse: ...


@dataclass
class Page:
    url: str
    final_url: str
    status: int
    content_type: str
    text: str
    bytes_read: int


BLOCK_STATUSES = {401, 403, 407, 429, 451}


class SafeFetcher:
    """The only path to the network. Every hop is guarded, counted and size-limited."""

    def __init__(self, transport: Transport, resolver: Resolver, request_timeout_s: float = 8.0):
        self.transport = transport
        self.resolver = resolver
        self.request_timeout_s = request_timeout_s

    def fetch(self, url: str, budget: Budget) -> Page:
        current = url
        for hop in range(budget.max_redirects + 1):
            budget.check()
            budget.allow_new_worker()
            resolved = resolve_public(
                current, self.resolver, max(0.1, min(self.request_timeout_s, budget.remaining)), budget.cancel,
                budget.note_abandoned,
            )
            response = self._get_with_retry(resolved, budget)
            try:
                if response.status in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    if not location:
                        raise FetchError("http_error", "redirect without location")
                    current = urljoin(current, location)
                    continue
                return self._read(url, current, response, budget)
            finally:
                response.close()
        raise FetchError("http_error", "too many redirects")

    def _read(self, url: str, current: str, response: RawResponse, budget: Budget) -> Page:
        if response.status in BLOCK_STATUSES:
            raise FetchError("blocked", f"http {response.status}")
        if response.status >= 400:
            raise FetchError("http_error", f"http {response.status}")
        ctype = response.headers.get("content-type", "").split(";")[0].strip().casefold()
        if ctype and not (ctype.startswith("text/") or "html" in ctype or "xml" in ctype):
            raise FetchError("http_error", "unsupported content type")
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > budget.max_bytes_per_page:
            raise FetchError("too_large", "declared size over limit")
        body = bytearray()
        try:
            for chunk in response.chunks:
                budget.check()
                body += chunk
                if len(body) > budget.max_bytes_per_page:
                    raise FetchError("too_large", "body over limit")
        except TransportTimeout:
            raise FetchError("timeout", "body read timed out") from None
        except TransportError:
            raise FetchError("fetch_error", "connection failed") from None
        budget.bytes += len(body)
        charset = "utf-8"
        if "charset=" in response.headers.get("content-type", ""):
            charset = response.headers["content-type"].split("charset=")[-1].strip() or "utf-8"
        try:
            text = bytes(body).decode(charset, errors="replace")
        except LookupError:
            text = bytes(body).decode("utf-8", errors="replace")
        return Page(url, current, response.status, ctype, text, len(body))

    def _get_with_retry(self, resolved: Resolved, budget: Budget) -> RawResponse:
        attempts = 0
        while True:
            budget.charge_page()
            timeout = max(0.1, min(self.request_timeout_s, budget.remaining))
            try:
                response = self.transport.get(resolved.url, timeout, resolved.ips)
            except TransportTimeout:
                outcome, detail = "timeout", "request timed out"
            except TransportError:
                outcome, detail = "fetch_error", "connection failed"
            else:
                if response.status < 500:
                    return response
                response.close()
                outcome, detail = "http_error", f"http {response.status}"
            if attempts >= budget.max_retries:
                raise FetchError(outcome, detail)
            attempts += 1


@dataclass
class Hit:
    url: str
    title: str = ""


@dataclass
class SearchQuery:
    capability: str
    trade: str | None
    facets: dict[str, str]
    limit: int


@dataclass
class SearchContext:
    """What an adapter may spend. It is told the remaining time and must watch cancel itself."""
    remaining_s: float
    cancel: threading.Event | None = None


class SearchAdapter(Protocol):
    source_id: str
    kind: str

    def search(self, query: SearchQuery, ctx: SearchContext) -> list[Hit]: ...


class StaticSearch:
    """Search results read from a recorded index. Titles are leads only and never become evidence."""

    def __init__(self, source_id: str, index: dict[str, list], kind: str = "fixture"):
        self.source_id = source_id
        self.kind = kind
        self.index = index

    def search(self, query: SearchQuery, ctx: SearchContext | None = None) -> list[Hit]:
        entry = self.index.get(query.capability, [])
        if entry == "__raise__":
            raise RuntimeError("fixture search adapter failure token=SECRET-SHOULD-NOT-LEAK C:\\private\\path")
        return [Hit(url=item["url"], title=item.get("title", "")) for item in entry][: query.limit]


class FixtureTransport:
    """Serves recorded and synthetic pages from fixtures/manifest.json. Not live traffic."""

    kind = "fixture"

    def __init__(self, directory: Path, advance_clock: Callable[[float], None] | None = None):
        self.directory = directory
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.pages: dict[str, dict] = manifest["pages"]
        self.calls: list[str] = []
        self.pinned: list[tuple[str, ...]] = []
        self.opened = 0
        self.closed = 0
        self.advance_clock = advance_clock
        self.after_call: Callable[[int], None] | None = None

    def get(self, url: str, timeout: float, pinned_ips: tuple[str, ...] = ()) -> RawResponse:
        self.calls.append(url)
        self.pinned.append(tuple(pinned_ips))
        if self.after_call:
            self.after_call(len(self.calls))
        entry = self.pages.get(url)
        if entry is None:
            return self._response(404, {"content-type": "text/html"}, iter([b"not found"]))
        delay = float(entry.get("delay_s", 0))
        if self.advance_clock and delay:
            self.advance_clock(min(delay, timeout))
        if delay > timeout:
            raise TransportTimeout()
        if entry.get("error") == "connection":
            raise TransportError()
        headers = {"content-type": "text/html; charset=utf-8", **entry.get("headers", {})}
        if "redirect" in entry:
            return self._response(entry.get("status", 302), {**headers, "location": entry["redirect"]}, iter([]))
        if "generate_bytes" in entry:
            body = b"<html><body>" + b"x" * int(entry["generate_bytes"]) + b"</body></html>"
        else:
            body = (self.directory / "pages" / entry["file"]).read_bytes()
        step = 8192
        return self._response(entry.get("status", 200), headers, (body[i:i + step] for i in range(0, len(body), step)))

    def _response(self, status: int, headers: dict[str, str], chunks: Iterator[bytes]) -> RawResponse:
        self.opened += 1
        return RawResponse(status, headers, chunks, on_close=self._count_close)

    def _count_close(self) -> None:
        self.closed += 1

    def fixture_resolver(self) -> Resolver:
        manifest = json.loads((self.directory / "manifest.json").read_text(encoding="utf-8"))
        table: dict[str, list[str]] = manifest.get("hosts", {})

        def resolve(host: str) -> list[str]:
            if host in table:
                return table[host]
            if host.endswith(".test"):
                return ["93.184.216.34"]
            raise FetchError("fetch_error", "dns lookup failed")

        return resolve


class HttpxTransport:
    """Live transport. Not used by tests against the network. Redirects are never followed here.

    It connects to the address SafeFetcher already validated, not to a fresh DNS answer, so the check and the
    connection cannot disagree. The request goes to the IP, with the original Host header and the original
    hostname as the TLS SNI and certificate name (httpx sni_hostname extension), so certificate checks still
    run against the real hostname. With no pinned address it refuses to connect.
    """

    kind = "live"
    MAX_ADDRESSES = 3

    def __init__(self, user_agent: str = "discovery-mcp-experiment/1.0 (contact: local experiment)", client_factory=None):
        import httpx

        self._httpx = httpx
        self.user_agent = user_agent
        self._factory = client_factory or (
            lambda timeout: httpx.Client(follow_redirects=False, timeout=timeout, headers={"User-Agent": self.user_agent})
        )

    def get(self, url: str, timeout: float, pinned_ips: tuple[str, ...] = ()) -> RawResponse:
        httpx = self._httpx
        if not pinned_ips:
            raise TransportError()
        parts = urlsplit(url)
        host = parts.hostname or ""
        host_header = host if parts.port in (None, 80, 443) else f"{host}:{parts.port}"
        failure: Exception = TransportError()
        for ip in pinned_ips[: self.MAX_ADDRESSES]:
            literal = f"[{ip}]" if ":" in ip else ip
            netloc = literal if parts.port is None else f"{literal}:{parts.port}"
            target = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
            client = self._factory(timeout)
            try:
                request = client.build_request(
                    "GET", target, headers={"Host": host_header}, extensions={"sni_hostname": host},
                )
                response = client.send(request, stream=True)
            except httpx.TimeoutException:
                client.close()
                raise TransportTimeout() from None
            except httpx.HTTPError:
                client.close()
                failure = TransportError()
                continue

            def chunks(response=response) -> Iterator[bytes]:
                try:
                    yield from response.iter_bytes()
                except httpx.HTTPError:
                    raise TransportError() from None

            def release(response=response, client=client) -> None:
                try:
                    response.close()
                finally:
                    client.close()

            headers = {k.lower(): v for k, v in response.headers.items()}
            return RawResponse(response.status_code, headers, chunks(), on_close=release)
        raise failure
