# Penny query routing

Penny interprets owner language and selects catalog task keys. The backend retrieves the corresponding recommendations and builds the permitted answer claims. Product facts, pricing, ownership and access checks remain server controlled.

## Routing and conversation state

- The latest turn's intent is selected before a catalog action. `respond_conversationally` is a separate model tool for greetings, acknowledgements, conversational repair, app help and scope explanations. It returns bounded natural text through the existing A2UI text surface, without product cards or memory updates. There is no input phrase list or canned greeting lookup.
- Conversational replies pass schema, length, secret-leak and input/output screening. They reject numeric amounts, URLs, known catalog product names, commercial assertions and claims of completed actions. These content checks are defense-in-depth heuristics, not proof that arbitrary prose is factually correct. Product questions continue through the evidence/claim selection path.
- A literal catalog phrase match is a hint. For an unfamiliar paraphrase, `recommend_tools` accepts a catalog `problem_id` and an exact affirmative `task_text` excerpt from a current or recent owner message. Assistant text cannot provide that excerpt. Explicit different tasks, ambiguous literal matches and negated clauses cannot be overridden by this path.
- The excerpt checks provenance, not semantic correctness. The model still makes the semantic classification. Catalog IDs and the resulting product claims are validated separately.
- A specific supported task is answered before optional intake. Missing business type or budget is represented as uncertainty, rather than forcing the owner through setup questions.
- `active_task_ids` and `pending_question` travel with the existing conversation memory and cache. New catalog resolutions update the active tasks. Several task actions in one turn keep their combined evidence and state. Earlier owner turns are used for pending background/plan answers, rather than treating every short message as continuation of an old task.
- A question that is already answered or present in recent history is withheld. When task evidence is available, Penny returns the approved answer. Otherwise the planner receives a bounded repair instruction to interpret the request or use the available no-match evidence.
- Task clarification requires two or three relevant, valid catalog IDs. Titles come from those catalog entries; there is no fallback to the first three tasks. A new chat clears the conversation state.

## Verification

`backend/tests/test_penny_routing.py` exercises paraphrases across several categories, the reservation-question loop and a complaint about repetition, known budget preservation, active-task state, multiple task actions, specific-task answers before intake, relevant clarification choices, fabricated excerpts, assistant-only excerpts, negation and conflicting tasks. Model responses are mocked for these offline tests; they do not prove live model behavior.

`backend/tests/test_penny_conversation.py` covers natural conversational replies after a previous task, preservation of memory, isolation from product actions, rejection of unsafe factual content and the secret-leak guard. It separately verifies that a short greeting no longer resolves to a prior task through the old message-length heuristic.

A bounded local OpenRouter replay of the reported conversation selected `appointment_booking`, returned a validated catalog answer and emitted no clarification question. The answer retained uncertainty about business suitability and pricing. This does not establish that appointment tools support telephone-based restaurant reservations. Paid checks use the existing persistent local ledger; its cap is independent of the provider key's own spending limit.

A subsequent local replay sent `hello` with an existing booking task and pending task question. Penny used the conversational tool, returned a natural greeting, and emitted no recommendation, clarification or memory update. This is one live sample; the parameterized conversation tests cover additional intents offline.
