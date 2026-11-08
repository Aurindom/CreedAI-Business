"""Bounded conversational replies, separate from catalog-backed product answers."""
import json
import re
from typing import Literal

from pydantic import Field, ValidationError

from . import chat_guard
from .agent.evidence import Strict
from .agent.grounding import FALLBACK, ValidatedReply


class ConversationReply(Strict):
    intent: Literal['greeting', 'acknowledgement', 'repair', 'help', 'scope']
    text: str = Field(min_length=1, max_length=600)


# This path is for conversation management, not a second product-facts channel.
_FACTUAL = re.compile(
    r'\d|[$\u00a3\u20ac%]|https?://|www\.|<[^>]*>|'
    r'\b(?:costs?|prices?|priced|integrat\w*|guarantee\w*|unlimited|cheapest|'
    r'includes?|supports?|provides?|offers?|certif\w*|compliant)\b|'
    r'\b(?:i|we)\s+(?:(?:have|just|already)\s+)*(?:saved|bought|purchased|connected|installed|configured|sent|verified)\b',
    re.I,
)

# Conversation replies end the turn. They cannot promise work that only a
# catalog action can perform, or announce results that were never produced.
_UNFULFILLED_ACTION = re.compile(
    r"\b(?:let me|let['\u2019]s|(?:i|we)(?:['\u2019]ll| will| am going to|'m going to| are going to))\b"
    r"[^.!?]{0,100}\b(?:get|find|fetch|look|search|check|recommend|compare|show|suggest|provide|pull)\b|"
    r"\bhere (?:are|is)\b[^.!?]{0,50}\b(?:recommendations?|options?|tools?|results?)\b",
    re.I,
)


def validate_conversation(raw, catalog, guard):
    wire = json.dumps(raw, default=str)
    if guard.leaks(wire):
        guard.tripped = True
        return ValidatedReply(status='blocked', text='That reply was blocked. Please try again.', reason='guard_intercepted')
    try:
        reply = ConversationReply.model_validate(raw)
    except ValidationError:
        return ValidatedReply(status='fallback', text=FALLBACK, reason='invalid_conversation_schema')
    text = reply.text.strip()
    if _UNFULFILLED_ACTION.search(text):
        return ValidatedReply(status='fallback', text=FALLBACK, reason='unfulfilled_action')
    product_names = [tool.name for tool in catalog.tools] + [tool.id for tool in catalog.tools]
    names_product = any(re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', text, re.I)
                        for name in product_names if name)
    if not text or _FACTUAL.search(text) or names_product or chat_guard.reason(text):
        return ValidatedReply(status='fallback', text=FALLBACK, reason='conversation_content_rejected')
    return ValidatedReply(status='validated', text=text)
