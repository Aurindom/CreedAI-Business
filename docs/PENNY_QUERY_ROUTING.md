# Penny query routing

Penny interprets owner language and selects catalog task keys. The backend retrieves the corresponding recommendations and builds the permitted answer claims. Product facts, pricing, ownership and access checks remain server controlled.

## Routing and conversation state

- A literal catalog phrase match is a hint. For an unfamiliar paraphrase, `recommend_tools` accepts a catalog `problem_id` and an exact affirmative `task_text` excerpt from a current or recent owner message. Assistant text cannot provide that excerpt. Explicit different tasks, ambiguous literal matches and negated clauses cannot be overridden by this path.
- The excerpt checks provenance, not semantic correctness. The model still makes the semantic classification. Catalog IDs and the resulting product claims are validated separately.
- A specific supported task is answered before optional intake. Missing business type or budget is represented as uncertainty, rather than forcing the owner through setup questions.
- `active_task_ids` and `pending_question` travel with the existing conversation memory and cache. New catalog resolutions update the active tasks. Several task actions in one turn keep their combined evidence and state. A pending background answer can retain its active task without guessing from message length alone.
- A question that is already answered or present in recent history is withheld. When task evidence is available, Penny returns the approved answer. Otherwise the planner receives a bounded repair instruction to interpret the request or use the available no-match evidence.
- Task clarification requires two or three relevant, valid catalog IDs. Titles come from those catalog entries; there is no fallback to the first three tasks. A new chat clears the conversation state.

## Verification

`backend/tests/test_penny_routing.py` exercises paraphrases across several categories, the reservation-question loop and a complaint about repetition, known budget preservation, active-task state, multiple task actions, specific-task answers before intake, relevant clarification choices, fabricated excerpts, assistant-only excerpts, negation and conflicting tasks. Model responses are mocked for these offline tests; they do not prove live model behavior.

A bounded local OpenRouter replay of the reported conversation selected `appointment_booking`, returned a validated catalog answer and emitted no clarification question. The answer retained uncertainty about business suitability and pricing. This does not establish that appointment tools support telephone-based restaurant reservations. Paid checks use the existing persistent local ledger; its cap is independent of the provider key's own spending limit.
