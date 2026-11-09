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


# The model chooses the conversational intent; the server owns the factual boundary.
# Arbitrary prose cannot be made safe by a denylist of vendor names or verbs.
APPROVED_REPLIES = {
    'greeting': ("Hi! I'm Arkadio. How can I help today?", "I'm here. What would you like to discuss?",
                 "I'm doing well, thanks! How are you?", 'Hello! How can I help?', 'Hello!'),
    'acknowledgement': ("You're welcome!", 'Happy to help.'),
    'repair': ("You're right to flag that. Let's focus on the part you want to work through.",),
    'help': ('I can help you compare business software and understand what you already use.',),
    'scope': ('I focus on business software. What would you like help with there?',),
}


def reply_choices():
    return {f'{intent}.{i}': text for intent, choices in APPROVED_REPLIES.items() for i, text in enumerate(choices)}


def app_help_reply(catalog, message, *, social=False):
    """Answer explicit app navigation questions from app-owned data, without a model.

    Anchored questions cannot swallow a substantive product request or resume
    earlier tasks. Business examples describe catalog navigation, not approval
    of every product for those businesses.
    """
    text = re.sub(r'\s+', ' ', message.casefold()).strip(' .!?')
    business_question = re.fullmatch(
        r'(?:what|which)(?: kinds? of| types? of)? (?:businesses|business|industries) (?:can|do) you (?:help|work|support)(?: me)?(?: with| for)?', text)
    if business_question:
        names = ', '.join(trade.name for trade in catalog.trades)
        return ('You can explore business software for these business types: ' + names +
                '. I help with everyday work such as scheduling, customer calls and bookkeeping. '
                'Which kind of business do you run?')
    if text in {'what can you do', 'what can you help me with', 'how can you help me',
                'how does this work', 'what is this website', 'what is creed ai'}:
        return ('I help you explore business software, compare options and plan your next steps. '
                'Tell me your type of business and one task you want to make easier, '
                'such as handling calls, scheduling or bookkeeping.')
    if social:
        if text in {'hello', 'hi', 'hey', 'hello arkadio', 'hi arkadio'}:
            return APPROVED_REPLIES['greeting'][0]
        if text in {'how are you', 'how are you doing'}:
            return APPROVED_REPLIES['greeting'][2]
        if text in {'thanks', 'thank you', 'thanks a lot'}:
            return APPROVED_REPLIES['acknowledgement'][0]
    return None


def business_intake(catalog, message):
    text = re.sub(r'\s+', ' ', message.casefold()).strip(' .!?')
    text = re.sub(r'^(?:help(?: me)? (?:with )?|i (?:run|own|have) (?:a |an )?)', '', text)
    text = re.sub(r' (?:issues|problems|business)$', '', text)
    if text == 'clinical':
        text = 'medical'
    return catalog.resolve_trade(text)


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
    approved = APPROVED_REPLIES[reply.intent]
    return ValidatedReply(status='validated', text=text if text in approved else approved[0])
