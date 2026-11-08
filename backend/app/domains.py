"""Who owns a web address. Discovery and the catalog seed use the same rule to spot the same product twice."""

import re
from urllib.parse import urlsplit

from .schemas import Tool

GENERIC_SECOND_LEVEL = {"co", "com", "org", "net", "ac", "gov", "edu", "ne", "or", "go", "gob", "nom", "ltd", "plc", "sch", "mil", "id"}
HOSTING_SUFFIXES = {
    "github.io", "gitlab.io", "vercel.app", "netlify.app", "herokuapp.com", "pages.dev", "workers.dev",
    "azurewebsites.net", "web.app", "firebaseapp.com", "onrender.com", "fly.dev", "appspot.com",
    "blogspot.com", "wordpress.com", "wixsite.com", "myshopify.com", "squarespace.com", "s3.amazonaws.com",
    "cloudfront.net", "azurestaticapps.net", "repl.co", "glitch.me", "carrd.co",
}

def registrable_domain(host: str) -> str:
    """Best effort owner domain without the full Public Suffix List, the same rule the discovery worker uses.

    Unlisted multi-label suffixes fall back to the last two labels and can merge unrelated owners.
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
    if ".".join(labels[-3:]) in HOSTING_SUFFIXES and len(labels) >= 4:
        return ".".join(labels[-4:])
    if len(labels[-1]) == 2 and labels[-2] in GENERIC_SECOND_LEVEL:
        return ".".join(labels[-3:])
    return tail2


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.casefold()).strip("-")


def identity(tool: Tool) -> tuple[str, str]:
    """Same owner domain and same product name means the same product, whatever id each side gave it."""
    return registrable_domain(urlsplit(str(tool.url)).hostname or ""), slug(tool.name)
