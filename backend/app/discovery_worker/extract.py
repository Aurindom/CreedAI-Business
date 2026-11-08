from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

from .contract import Snapshot

SKIP_TAGS = {"script", "style", "noscript", "template", "svg"}
GENERIC_HEADINGS = {"pricing", "plans", "plans and pricing", "plans & pricing", "home", "welcome", "features", "product", "overview"}
BLOCK_MARKERS = ("access denied", "verify you are human", "captcha", "are you a robot", "unusual traffic")
SIDE_TAGS = {"nav": "navigation", "footer": "navigation", "aside": "navigation", "menu": "navigation", "blockquote": "review"}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class _Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.h1: list[str] = []
        self.meta: dict[str, str] = {}
        self.canonical: str | None = None
        self.links: list[tuple[str, str]] = []
        self.scripts = 0
        self.text: list[str] = []
        self.side: list[tuple[str, str]] = []
        self._side_stack: list[tuple[str, str]] = []
        self._side_buf: list[str] = []
        self._side_kind = "navigation"
        self._skip = 0
        self._in_title = False
        self._in_h1 = False
        self._in_a: str | None = None
        self._a_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = {k: (v or "") for k, v in attrs}
        if tag == "script":
            self.scripts += 1
        side_kind = SIDE_TAGS.get(tag)
        if side_kind:
            if not self._side_stack:
                self._side_buf = []
            if not self._side_stack:
                self._side_kind = side_kind
            self._side_stack.append((tag, side_kind))
        if tag in SKIP_TAGS:
            self._skip += 1
        if tag == "title":
            self._in_title = True
        elif tag == "h1":
            self._in_h1 = True
            self.h1.append("")
        elif tag == "meta":
            key = a.get("property") or a.get("name")
            if key and "content" in a:
                self.meta[key.casefold()] = a["content"]
        elif tag == "link" and a.get("rel", "").casefold() == "canonical":
            self.canonical = a.get("href")
        elif tag == "a" and a.get("href"):
            self._in_a = a["href"]
            self._a_text = []

    def handle_endtag(self, tag):
        if self._side_stack and self._side_stack[-1][0] == tag:
            _, kind = self._side_stack.pop()
            if not self._side_stack and self._side_buf:
                self.side.append((self._side_kind, " ".join(self._side_buf)))
                self._side_buf = []
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False
        elif tag == "a" and self._in_a is not None:
            self.links.append((self._in_a, " ".join(self._a_text).strip()))
            self._in_a = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if self._side_stack:
            self._side_buf.append(data)
            return
        if self._in_h1 and self.h1:
            self.h1[-1] += data
        if self._in_a is not None:
            self._a_text.append(data)
        self.text.append(data)


def clean(text: str, limit: int = 200) -> str:
    return re.sub(r"\s+", " ", CONTROL.sub("", text)).strip()[:limit]


@dataclass
class Facts:
    outcome: str = "ok"
    vendor: str | None = None
    product: str | None = None
    canonical_url: str | None = None
    pricing_link: str | None = None
    capabilities: list[str] = field(default_factory=list)
    facets: dict[str, list[str]] = field(default_factory=dict)
    applicability: str = "unknown"
    applicability_trades: list[str] = field(default_factory=list)
    plans: list[dict] = field(default_factory=list)
    usage: list[dict] = field(default_factory=list)
    quote_only: bool = False
    hypotheses: dict[str, str] = field(default_factory=dict)
    not_offered: list[str] = field(default_factory=list)
    evidence: list[dict] = field(default_factory=list)
    text_len: int = 0


GENERIC_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go", "gob", "nom", "ltd", "plc", "sch", "mil", "id"}
HOSTING_SUFFIXES = {
    "github.io", "gitlab.io", "vercel.app", "netlify.app", "herokuapp.com", "pages.dev", "workers.dev",
    "azurewebsites.net", "web.app", "firebaseapp.com", "onrender.com", "fly.dev", "appspot.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "myshopify.com", "squarespace.com", "s3.amazonaws.com",
    "cloudfront.net", "azurestaticapps.net", "repl.co", "glitch.me", "carrd.co",
}


def registrable_domain(host: str) -> str:
    """Best effort registrable domain without the full Public Suffix List.

    Handles three cases the naive last-two-labels rule gets wrong: ccTLD second levels such as co.uk and
    com.au (any two-letter TLD whose second level is a generic word, so unlisted ones like co.zw also work),
    and a bounded list of shared hosting suffixes where each subdomain is a different owner (github.io).
    It cannot cover every suffix in the real list, such as city.kawasaki.jp or private suffixes not named
    here. For those it falls back to the last two labels, which can merge unrelated owners, so a candidate
    on an unknown suffix should be treated as lower trust until a real PSL is installed.
    """
    host = host.casefold().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    tail2 = ".".join(labels[-2:])
    if tail2 in HOSTING_SUFFIXES:
        return ".".join(labels[-3:])
    if any(".".join(labels[-n:]) in HOSTING_SUFFIXES for n in (3,)) and len(labels) >= 4:
        return ".".join(labels[-4:])
    if len(labels[-1]) == 2 and labels[-2] in GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return tail2


def phrase_regex(phrase: str) -> re.Pattern:
    tokens = [re.escape(t) for t in phrase.casefold().replace("_", " ").split()]
    if tokens and len(tokens[-1]) > 3:
        tokens[-1] += "s?"
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(tokens) + r"(?![a-z0-9])")


def snippet(text: str, start: int, end: int, pad: int = 70) -> str:
    return clean(text[max(0, start - pad): end + pad], 220)


CODES = "CAD|USD|AUD|NZD|EUR|GBP|SGD|INR"
SYMBOL_CURRENCY = {"US$": "USD", "CA$": "CAD", "C$": "CAD", "AU$": "AUD", "A$": "AUD", "NZ$": "NZD", "€": "EUR", "£": "GBP", "$": None}
PRICE = re.compile(
    r"(?:(?P<name>[A-Z][A-Za-z]{2,20})\s*(?:plan)?\s*[:\-]?\s*)?"
    r"(?P<pre>(?:" + CODES + r")\s*)?(?P<sym>US\$|CA\$|C\$|AU\$|A\$|NZ\$|\$|€|£)\s?(?P<amt>\d{1,3}(?:,\d{3})*(?:\.\d{1,3})?)\s*"
    r"(?P<post>(?:" + CODES + r")\b\s*)?(?:/|per\s+|a\s+)\s*(?P<unit>[A-Za-z]+(?:\s*/\s*[A-Za-z]+|\s+per\s+[A-Za-z]+)?)"
)


def resolve_currency(symbol: str, pre: str | None, post: str | None) -> str | None:
    """A bare dollar sign is ambiguous (USD, CAD, AUD and others), so it stays None unless a code is printed."""
    codes = {c.strip().upper() for c in (pre, post) if c and c.strip()}
    from_symbol = SYMBOL_CURRENCY.get(symbol)
    if from_symbol:
        codes.add(from_symbol)
    return codes.pop() if len(codes) == 1 else None


PLAN_UNITS = {"month", "mo", "year", "yr", "user/month", "user per month", "seat/month", "location/month", "user/mo", "user/year"}
NOT_PLAN_NAMES = {"From", "Only", "Just", "Starting", "Plans", "Price", "Pricing", "Billed", "Then", "Extra", "Plus", "Add", "Pay", "Costs", "Cost"}
ANNUAL = re.compile(r"billed\s+(?:annually|yearly)|annual\s+billing|paid\s+(?:annually|yearly)|billed\s+once\s+a\s+year", re.I)
MONTHLY = re.compile(r"billed\s+monthly|month[\s-]to[\s-]month|monthly\s+billing", re.I)
QUOTE = re.compile(r"contact\s+(?:our\s+)?sales|request\s+a\s+(?:quote|demo\s+for\s+pricing)|custom\s+pricing|get\s+a\s+quote|talk\s+to\s+sales|pricing\s+on\s+request", re.I)


CLAUSE_BREAK = re.compile(r"[.!?;:\n]|\b(?:but|however|although|though|while|whereas|yet|except)\b")
NEG_BEFORE = re.compile(
    r"\b(?:do(?:es)?\s+not|did\s+not|don't|doesn't|didn't|cannot|can\s?not|can't|will\s+not|won't|never|no\s+longer|"
    r"not\s+(?:currently\s+|yet\s+)?(?:offer|provide|support|include|handle|have|available|do)|"
    r"(?:is|are)\s+not|isn't|aren't|without|unable\s+to|lacks?|neither|nor)\b"
)
NO_DIRECT = re.compile(r"\bno\s+(?:\w+\s+)?$")
NEG_AFTER = re.compile(
    r"^\W*(?:\w+\s+){0,3}?(?:(?:is|are|was|were)\s+(?:not|no\s+longer)\s+(?:available|supported|offered|included|provided)|"
    r"(?:is|are)\s+unavailable|not\s+(?:available|supported|offered|included)|has\s+been\s+discontinued|is\s+discontinued)"
)
SOON = re.compile(
    r"coming\s+soon|planned|roadmap|will\s+(?:soon\s+)?(?:be\s+)?(?:launch|available|support|offer|add)|"
    r"(?:in|under)\s+development|waitlist|join\s+the\s+beta|beta\s+soon|not\s+yet|upcoming|later\s+this"
)
COMPARE = re.compile(
    r"\bvs\.?\b|versus|compared\s+(?:to|with)|comparison|alternatives?\s+to|better\s+than|unlike|instead\s+of|"
    r"competitors?|switch(?:ing)?\s+from|rather\s+than|other\s+tools"
)
REVIEWISH = re.compile(r"\breviews?\b|testimonials?|customers?\s+(?:say|said|tell)|\bsays\b|\bsaid\b|[\"“”]|\bstars?\b|\brated\b|\bwrote\b")
SENT_END = ".!?;\n"


def classify_mention(lowered: str, start: int, end: int) -> str:
    """How a phrase is used at one position: positive, negated, coming_soon, comparison or review.

    Heuristic and local to one sentence. It reads the words just before and after the phrase for negation,
    then the whole sentence for roadmap, comparison and review wording. Anything it cannot place is positive,
    so a clever negation it misses can still be read as support. That is why every result stays a research
    candidate and the evidence excerpt is always kept.
    """
    left = max((lowered.rfind(ch, 0, start) for ch in SENT_END), default=-1) + 1
    rights = [i for i in (lowered.find(ch, end) for ch in SENT_END) if i != -1]
    right = min(rights) if rights else len(lowered)
    before = lowered[left:start]
    breaks = list(CLAUSE_BREAK.finditer(before))
    clause_before = before[breaks[-1].end():] if breaks else before
    words_before = " ".join(clause_before.split()[-6:]) + " "
    if NEG_BEFORE.search(words_before) or NO_DIRECT.search(" ".join(clause_before.split()[-2:]) + " "):
        return "negated"
    if NEG_AFTER.search(lowered[end:right + 1]):
        return "negated"
    sentence = lowered[left:right]
    if SOON.search(sentence):
        return "coming_soon"
    if COMPARE.search(sentence):
        return "comparison"
    if REVIEWISH.search(sentence):
        return "review"
    return "positive"


def scan_phrase(lowered: str, pattern: re.Pattern) -> tuple[re.Match | None, dict[str, re.Match]]:
    """Return the first positive match and the first match of each other context."""
    first_positive: re.Match | None = None
    others: dict[str, re.Match] = {}
    for m in pattern.finditer(lowered):
        kind = classify_mention(lowered, m.start(), m.end())
        if kind == "positive":
            first_positive = first_positive or m
        else:
            others.setdefault(kind, m)
    return first_positive, others


def judge(facts: "Facts", key: str, text: str, lowered: str, side: list[tuple[str, str]], patterns: list[re.Pattern]) -> bool:
    """Record one claim as verified, explicitly not offered, or only a hypothesis. True means verified."""
    others: dict[str, re.Match] = {}
    for pattern in patterns:
        positive, found = scan_phrase(lowered, pattern)
        if positive:
            facts.evidence.append({"field": key, "excerpt": snippet(text, positive.start(), positive.end())})
            return True
        for kind, m in found.items():
            others.setdefault(kind, m)
    if "negated" in others:
        m = others["negated"]
        facts.not_offered.append(key)
        facts.evidence.append({"field": f"not_offered.{key}", "excerpt": snippet(text, m.start(), m.end())})
        return False
    for kind in ("coming_soon", "comparison", "review"):
        if kind in others:
            m = others[kind]
            facts.hypotheses[key] = kind
            facts.evidence.append({"field": f"hypothesis.{key}", "excerpt": snippet(text, m.start(), m.end())})
            return False
    for kind, side_text in side:
        side_lower = side_text.casefold()
        for pattern in patterns:
            m = pattern.search(side_lower)
            if m:
                facts.hypotheses[key] = kind
                facts.evidence.append({"field": f"hypothesis.{key}", "excerpt": snippet(side_text, m.start(), m.end())})
                return False
    return False


def extract_pricing(text: str, url: str) -> tuple[list[dict], list[dict], bool, list[dict]]:
    plans: list[dict] = []
    usage: list[dict] = []
    evidence: list[dict] = []
    seen: set[tuple] = set()
    for m in PRICE.finditer(text):
        amount = float(m.group("amt").replace(",", ""))
        name = m.group("name")
        pre = m.group("pre")
        if name and name.upper() in CODES.split("|") and not pre:
            pre, name = name, None
        currency = resolve_currency(m.group("sym"), pre, m.group("post"))
        unit = re.sub(r"\s+", " ", m.group("unit").strip().casefold())
        unit = unit.replace(" / ", "/")
        window = text[max(0, m.start() - 90): m.end() + 110]
        key = (round(amount, 3), unit, name, currency)
        if key in seen:
            continue
        seen.add(key)
        if unit in PLAN_UNITS or re.search(r"\b(month|mo|year|yr)\b", unit):
            billing = "annual" if ANNUAL.search(window) else "monthly" if MONTHLY.search(window) else "unspecified"
            plans.append({
                "name": None if name in NOT_PLAN_NAMES else name, "amount": amount, "currency": currency,
                "unit": unit, "billing": billing, "source_url": url,
            })
            evidence.append({"field": "pricing.plan", "excerpt": snippet(text, m.start(), m.end())})
        else:
            usage.append({"amount": amount, "currency": currency, "per": unit, "source_url": url})
            evidence.append({"field": "pricing.usage", "excerpt": snippet(text, m.start(), m.end())})
    q = QUOTE.search(text)
    if q:
        evidence.append({"field": "pricing.quote_only", "excerpt": snippet(text, q.start(), q.end())})
    return plans, usage, bool(q), evidence


def extract_page(html: str, page_url: str, snapshot: Snapshot) -> Facts:
    parser = _Parser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        return Facts(outcome="needs_rendering")
    text = re.sub(r"\s+", " ", " ".join(parser.text)).strip()
    facts = Facts(text_len=len(text))
    lowered = text.casefold()
    if len(text) < 600 and any(marker in lowered for marker in BLOCK_MARKERS):
        facts.outcome = "blocked"
        return facts
    if len(text) < 20:
        facts.outcome = "needs_rendering" if parser.scripts else "no_identity"
        return facts

    host = urlsplit(page_url).hostname or ""
    domain = registrable_domain(host)
    facts.vendor = clean(parser.meta.get("og:site_name", ""), 80) or domain.split(".")[0].capitalize()
    heading = next((clean(h, 80) for h in parser.h1 if clean(h, 80)), "")
    og_title = clean(parser.meta.get("og:title", ""), 80)
    generic = heading.casefold() in GENERIC_HEADINGS
    facts.product = heading if heading and not generic else (og_title if og_title.casefold() not in GENERIC_HEADINGS else None) or None
    if parser.canonical:
        canon = urljoin(page_url, parser.canonical)
        if registrable_domain(urlsplit(canon).hostname or "") == domain:
            facts.canonical_url = canon
    for href, label in parser.links:
        if re.search(r"\b(pricing|plans)\b", label, re.I) or re.search(r"/(pricing|plans)\b", href, re.I):
            target = urljoin(page_url, href)
            if registrable_domain(urlsplit(target).hostname or "") == domain and urlsplit(target).scheme in ("http", "https"):
                facts.pricing_link = target
                break

    for cap in sorted(snapshot.capabilities):
        if judge(facts, f"capability.{cap}", text, lowered, parser.side, [phrase_regex(p) for p in snapshot.phrases(cap)]):
            facts.capabilities.append(cap)
    for fid, facet in snapshot.facets.items():
        found: list[str] = []
        for value in sorted(facet["values"]):
            if judge(facts, f"facet.{fid}.{value}", text, lowered, parser.side, [phrase_regex(value)]):
                found.append(value)
        if found:
            facts.facets[fid] = found

    named: list[str] = []
    for tid, name in sorted(snapshot.trades.items()):
        if judge(facts, f"trade.{tid}", text, lowered, parser.side, [phrase_regex(name), phrase_regex(tid)]):
            named.append(tid)
    if len(named) >= 3:
        facts.applicability, facts.applicability_trades = "cross_industry", named
    elif named:
        facts.applicability, facts.applicability_trades = "restricted", named

    facts.plans, facts.usage, facts.quote_only, price_evidence = extract_pricing(text, page_url)
    facts.evidence.extend(price_evidence)
    return facts
