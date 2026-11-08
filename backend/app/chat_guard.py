"""Bounded, deterministic checks around the model. These are defense in depth, not an injection proof."""
import html
import ipaddress
import logging
import os
import re
import threading
import time
import unicodedata
from collections import deque

logger = logging.getLogger("penny.guard")
BLOCKED_INSTRUCTIONS = "I can help with business tools, but I cannot follow instructions to bypass safeguards or reveal private instructions. Please ask about the task or tools you want to compare."
BLOCKED_PERSONAL = "Please remove email addresses, phone numbers, card or account numbers, ID numbers, passwords and keys before sending. Describe the business task without personal or payment details."
_EMAIL = re.compile(r"\b[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9](?:[A-Z0-9.-]*[A-Z0-9])?\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<![\w$])(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
_INJECTIONS = [
    re.compile(r"\b(?:ignore|disregard|override|bypass|forget)\b.{0,60}\b(?:instructions?|rules?|safeguards?|system|previous|above|prior)\b", re.I),
    re.compile(r"\b(?:reveal|show|print|repeat|expose|leak|return|display)\b.{0,55}\b(?:system\s*(?:prompt|message)|developer\s*(?:prompt|message)|(?:your|hidden|private|internal|original)\s+(?:prompt|instructions?)|api\s*key|secret\s*key)\b", re.I),
    re.compile(r"(?:<\|(?:im_start|system|developer)|\[INST\]|(?:^|\n)\s*(?:SYSTEM|DEVELOPER)\s*:)", re.I),
    re.compile(r"\b(?:send|post|upload|exfiltrate)\b.{0,60}\b(?:keys?|secrets?|tokens?|credentials?|conversation|chat\s*history)\b", re.I),
    # Persona jailbreaks: "you are now DAN", "developer mode", "act as an unfiltered AI".
    re.compile(r"\b(?:you\s+are|you're)\s+now\b.{0,60}\b(?:DAN|unrestricted|unfiltered|uncensored|jailbroken|no\s+(?:rules|restrictions|limits|guidelines|filters))\b", re.I),
    re.compile(r"\b(?:developer|god|debug|jailbreak|DAN|unrestricted)\s+mode\b", re.I),
    re.compile(r"\b(?:act|behave|pretend|roleplay|role-play)\b.{0,50}\b(?:unfiltered|unrestricted|uncensored|jailbroken|(?:no|without)\s+(?:rules|restrictions|limits|guidelines|filters))\b", re.I),
    re.compile(r"\bnew\s+(?:system\s+)?(?:instructions?|rules|prompt)\s*:", re.I),
    re.compile(r"\b(?:what\s+(?:are|is|were)|tell\s+me|list)\b.{0,20}\byour\s+(?:system\s+)?(?:instructions?|prompt|rules|guidelines)\b", re.I),
    re.compile(r"\b(?:decode|base64)\b.{0,40}\b(?:follow|execute|run|obey)\b", re.I),
    # The same override in Spanish, French, German and Portuguese.
    re.compile(r"\b(?:ignora|ignore[zr]?|ignoriere|olvida|oublie[zr]?|vergiss|esque[cç]a)\b.{0,60}\b(?:instrucciones|instruções|instructions|anweisungen|reglas|règles|regeln|regras)\b", re.I),
]

def normalized(text: str) -> str:
    text = html.unescape(unicodedata.normalize("NFKC", text))
    return "".join(c for c in text if unicodedata.category(c) != "Cf")

def instruction_attempt(text: str) -> bool:
    clean = normalized(text)
    spaced = "".join(" " if unicodedata.category(c) == "Cf" else c for c in html.unescape(unicodedata.normalize("NFKC", text)))
    # Test both joined and separated words; zero-width characters can disguise either.
    variants = [clean, spaced, re.sub(r"\s+", " ", clean), re.sub(r"\s+", " ", spaced)]
    return any(pattern.search(value) for pattern in _INJECTIONS for value in variants)

_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b(?:ssn|social\s+security(?:\s+(?:number|no\.?))?)\D{0,15}\d{9}\b", re.I)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){2,7}(?:\s?[A-Z0-9]{1,3})?\b")
_SECRET = re.compile(
    r"\b(?:sk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_-]{16,}|sb_secret_[A-Za-z0-9_-]{10,}|gh[pousr]_[A-Za-z0-9]{20,}"
    r"|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9-]{10,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,})"
    r"|\b(?:password|passcode|passwd)\s*(?:is|:|=)\s*\S{4,}", re.I)


def _luhn(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char) * (2 if index % 2 else 1)
        total += value - 9 if value > 9 else value
    return total % 10 == 0


def _iban_valid(text: str) -> bool:
    code = re.sub(r"\s", "", text).upper()
    moved = code[4:] + code[:4]
    return 15 <= len(code) <= 34 and int("".join(str(int(char, 36)) for char in moved)) % 97 == 1


def payment_or_credential(text: str) -> bool:
    """Card numbers (Luhn-checked), US Social Security numbers, IBANs (checksum-verified), passwords and API keys."""
    clean = normalized(text)
    if any(_luhn(re.sub(r"\D", "", match.group())) for match in _CARD.finditer(clean)):
        return True
    if _SSN.search(clean) or _SECRET.search(clean):
        return True
    return any(_iban_valid(match.group()) for match in _IBAN.finditer(clean))


def personal_data(text: str) -> bool:
    clean = normalized(text)
    if _EMAIL.search(clean) or payment_or_credential(clean):
        return True
    for match in _PHONE.finditer(clean):
        candidate = match.group()
        digits = re.sub(r"\D", "", candidate)
        if 10 <= len(digits) <= 15 and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", candidate):
            return True
    return False

def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)

def reason(value, *, include_personal=True):
    for text in strings(value):
        if instruction_attempt(text):
            return "prompt_injection"
        if include_personal and personal_data(text):
            return "personal_data"
    return None

def audit(reason_code: str, source: str):
    # Fixed enums only: never text, IPs, tokens, headers, tool content, or exception arguments.
    allowed_reasons = {"prompt_injection", "personal_data", "rate_limit", "tool_injection", "output_blocked", "unknown_action", "invented_price", "catalog_injection"}
    allowed_sources = {"message", "history", "profile", "tool", "output", "catalog", "limiter"}
    logger.warning("penny_guard_block", extra={"guard_reason": reason_code if reason_code in allowed_reasons else "output_blocked", "guard_source": source if source in allowed_sources else "output"})

def check_request(body):
    fields = [("message", body.message), ("history", [item.text for item in body.history]), ("profile", {"trade": body.profile.trade, "plans": [entry.plan for entry in body.profile.owned], "memory_trade": body.memory.trade})]
    for source, value in fields:
        found = reason(value)
        if found:
            audit(found, source)
            return BLOCKED_PERSONAL if found == "personal_data" else BLOCKED_INSTRUCTIONS
    return None

def safe_catalog_text(text: str) -> str:
    if instruction_attempt(text):
        audit("catalog_injection", "catalog")
        return "[Catalog text withheld because it contains instructions.]"
    return text

def client_id(request):
    peer = request.client.host if request.client else "unknown"
    try:
        peer_ip = ipaddress.ip_address(peer)
    except ValueError:
        return "unknown"
    if os.environ.get("CHAT_TRUST_PROXY") != "1":
        return str(peer_ip)
    networks = []
    for value in os.environ.get("CHAT_TRUSTED_PROXY_CIDRS", "").split(","):
        try:
            networks.append(ipaddress.ip_network(value.strip()))
        except ValueError:
            continue
    def trusted(ip):
        return any(ip in network for network in networks)
    if not trusted(peer_ip):
        return str(peer_ip)
    forwarded = request.headers.get("x-forwarded-for", "")
    if not forwarded or len(forwarded) > 1024:
        return str(peer_ip)
    try:
        chain = [ipaddress.ip_address(part.strip()) for part in forwarded.split(",")] + [peer_ip]
    except ValueError:
        return str(peer_ip)
    while len(chain) > 1 and trusted(chain[-1]):
        chain.pop()
    return str(chain[-1])

class BurstLimiter:
    def __init__(self, max_clients=5000):
        self.lock = threading.Lock()
        self.clients = {}
        self.max_clients = max_clients

    def allow(self, client, limit, now=None):
        now = time.monotonic() if now is None else now
        with self.lock:
            if client not in self.clients and len(self.clients) >= self.max_clients:
                self.clients = {key: times for key, times in self.clients.items() if times and times[-1] > now - 60}
                if len(self.clients) >= self.max_clients:
                    return False
            times = self.clients.setdefault(client, deque())
            while times and times[0] <= now - 60:
                times.popleft()
            if len(times) >= limit:
                return False
            times.append(now)
            return True
