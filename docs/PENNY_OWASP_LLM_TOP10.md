# Penny and the OWASP Top 10 for LLM Applications (2025)

How Penny, the chat assistant, handles each OWASP LLM risk, and which tests prove it.
Tests: `backend/tests/test_owasp_llm_guardrails.py` (offline: the model's moves are scripted, so they cost nothing).

## The core design

The model never writes text the owner sees. For product answers it selects claim IDs from an evidence
package the backend built from the catalog; the backend writes the words, prices and links. For small talk it
picks an intent and the server shows one of its own approved replies. Input checks sit on top of that as
defense in depth, so a jailbreak that slips past them still cannot make Penny say anything new.

| OWASP item | How Penny handles it | Proof |
|---|---|---|
| **LLM01 Prompt injection** | Input guard on the message, history and profile: override, reveal-prompt, role markers, exfiltration, persona jailbreaks ("you are now DAN", "developer mode", "act as unfiltered"), "new instructions:", base64 tricks, and overrides in Spanish, French, German and Portuguese. Hidden and full-width characters are normalized first. Catalog text with instructions is withheld; tool arguments are checked. | `test_llm01_*` |
| **LLM02 Sensitive information disclosure** | Emails, phone numbers, card numbers (Luhn-checked), US Social Security numbers, IBANs (checksum-verified), passwords and API keys are refused before anything goes to the model provider. Provider keys never reach the model, and an echoed key is caught on the way out. Logs record fixed reason codes, never text. | `test_llm02_*` |
| **LLM03 Supply chain** | Model pinned (`anthropic/claude-haiku-4.5`); Hermes version pinned; catalog is reviewed data, not live web text. | Code review |
| **LLM04 Data and model poisoning** | Discovered tools enter as "Pending review" and can never be the recommended winner; automatic verification needs exact vendor quotations. | Existing discovery and matching tests |
| **LLM05 Improper output handling** | Model prose is never rendered; React escapes all text; links pass a safe-URL check; only allow-listed A2UI components render. | `test_llm05_*` |
| **LLM06 Excessive agency** | The model can call only listed read-only actions; anything else is refused. Penny cannot buy, sign up, email or change accounts. Saving a plan needs a signed-in owner and a server-side check. | `test_llm06_*` |
| **LLM07 System prompt leakage** | Requests for the prompt are refused; model-written text that quotes it is replaced by server text. | `test_llm01_*`, `test_llm05_llm07_*` |
| **LLM08 Vector and embedding weaknesses** | Not applicable: Penny uses no vector store; lookups are exact catalog IDs. | n/a |
| **LLM09 Misinformation** | Only approved, sourced claims render; unknown facts stay "check with the vendor"; invented claim IDs are dropped. | `test_llm09_*` |
| **LLM10 Unbounded consumption** | 500-character messages, 12 history items, 3 model rounds, 800 output tokens, 30 requests a minute and 60 a day per visitor, 3 chats at once, and a lifetime spending cap (`CHAT_SPEND_CAP_USD`). | `test_llm10_*`, existing cap and in-flight tests |

## Known limits

- The input guard is pattern-based. New phrasings or other languages can get past it; the core design is
  what keeps that harmless.
- Any 10 to 15 digit number is treated as a possible phone number, so long order numbers are refused too.
- Street addresses and names are not detected.
- These tests script the model. A live red-team run against the real model costs money and needs budget approval.
